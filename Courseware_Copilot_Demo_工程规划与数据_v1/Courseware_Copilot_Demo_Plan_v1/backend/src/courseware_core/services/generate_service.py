"""T09 候选生成与语义核验：GenerateService（docs/18 Generator/Verifier 契约）。

- create_generate_job：受理门禁——consent + 权威确认计划接缝（R00-C 精确三要素，
  绝不猜"最新确认"）+ base_version CAS 前置；参数（plan_id/base_version）落
  jobs 内部列 params_json，执行侧按 job 精确取参。
- handle_generate：每批 2–3 页 ContentProposal（docs/06:25）→ locator 转存储
  Claim（引用定位失败给一次修复，仍失败=invalid）→ 批次语义核验（未被定位的
  claim 不进模型队列——模型 verdict 不得掩盖定位失败，docs/18:43；零 fact 批
  不调语义模型）→ 结构/关系检查 → can_commit 可执行门（docs/04:41）→
  CandidateChange（ready/blocked）落 changes。
- 生成与应用分离：本服务从不触碰 current_version；只有 commit 经
  VersionRepository CAS 原子前进版本。blocked 候选保留给教师看报告——
  补材料或收窄目标后重新受理生成，不自动改写教师确认的事实范围。
"""

import hashlib
import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from courseware_core.errors import (
    ChangeNotCommittable,
    ChangeNotFound,
    ConsentRequired,
    CorpusChanged,
    DomainError,
    ModelOutputInvalid,
    ModelProtocolError,
    ProjectNotFound,
    VersionConflict,
)
from courseware_core.evidence.locator import resolve_evidence
from courseware_core.jobs.execution_guard import (
    build_job_context,
    guard_active,
    guard_writable,
)
from courseware_core.llm.prompts import load_system_prompt
from courseware_core.models import (
    CandidateChange,
    Claim,
    ClaimVerification,
    CommitRequest,
    ContentProposal,
    DeckSpec,
    DeckVersion,
    GenerateRequest,
    IllustrationBlock,
    Job,
    JobAccepted,
    JobResultRef,
    Slide,
    UnboundAssertion,
    ValidationReport,
)
from courseware_core.retrieval.bm25 import search_chunks
from courseware_core.retrieval.context import select_evidence_within_budget
from courseware_core.services.claim_verdicts import map_verdicts, verdicts_to_checks
from courseware_core.services.coverage_service import TOP_K
from courseware_core.services.edit_patch import relations_valid
from courseware_core.services.generate_messages import (
    audit_messages,
    content_messages,
    verify_messages,
)
from courseware_core.services.idempotency_service import OperationBinder
from courseware_core.services.plan_service import PlanService
from courseware_core.storage.change_repository import ChangeRepository
from courseware_core.storage.job_repository import JobRepository
from courseware_core.storage.project_repository import ProjectRepository
from courseware_core.storage.version_repository import VersionRepository

# docs/06:25 每批 2—3 页；预算与 plan 同源（docs/05 §9 公平装配）。
BATCH_SLIDES_MAX = 3
PAGE_CHUNK_MAX = 8
BATCH_CHAR_BUDGET = 8000
# docs/06:31 一次生成最多 24 次实际模型请求（含重试、修复和复核）。
GENERATE_CALL_BUDGET = 24


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_change_id() -> str:
    return f"chg_{secrets.token_hex(16)}"


def canonical_sha(payload) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class GenerateService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        provider=None,
        prompts_dir: Optional[Path] = None,
        model_id: Optional[str] = None,
    ):
        self._conn = conn
        self._provider = provider
        self._prompts_dir = prompts_dir
        # ValidationReport.model_id：None=unknown（不写假值，与 usage 口径一致）。
        self._model_id = model_id
        self._changes = ChangeRepository(conn)
        self._jobs = JobRepository(conn)
        self._projects = ProjectRepository(conn)
        self._versions = VersionRepository(conn)
        # 接缝复用 PlanService（同 conn）：确认计划的权威读取只有一个实现。
        self._plans = PlanService(conn)

    # ---------- 受理 ----------

    def create_generate_job(
        self,
        project_id: str,
        request: GenerateRequest,
        request_id: Optional[str] = None,
        binder: Optional[OperationBinder] = None,
    ) -> JobAccepted:
        project = self._projects.get(project_id)
        if project is None:
            raise ProjectNotFound({"project_id": project_id})
        self._require_cloud_consent(project)
        # 消费 R00-C 精确接缝：plan 必须存在、属本项目、confirmed、三要素一致。
        plan = self._plans.get_confirmed_plan_for_generation(
            project_id, request.plan_id, request.corpus_revision
        )
        # 生成基于教师当前看到的版本；视图落后/超前都要显式冲突，不静默改基。
        if request.base_version != project.current_version:
            raise VersionConflict(
                {"requested": request.base_version, "current": project.current_version}
            )
        job_id = f"job_{secrets.token_hex(16)}"
        params = json.dumps(
            {"plan_id": plan.id, "base_version": request.base_version},
            ensure_ascii=False,
        )
        anchor = (lambda conn: binder.bind(job_id)) if binder is not None else None
        self._changes.create_generate_job(
            project_id, job_id=job_id, corpus_revision=request.corpus_revision,
            params_json=params, request_id=request_id, on_committed=anchor,
        )
        return JobAccepted(job_id=job_id)

    @staticmethod
    def _require_cloud_consent(project) -> None:
        if not project.consent_to_cloud_processing:
            raise ConsentRequired({"project_id": project.id})

    # ---------- worker 执行 ----------

    def handle_generate(self, job: Job) -> JobResultRef:
        project = self._projects.get(job.project_id)
        if project is None:
            raise ProjectNotFound({"project_id": job.project_id})
        # 纵深复核：受理已拦，旁路/旧队列进来的 job 在任何模型调用前再拦一次。
        self._require_cloud_consent(project)
        if job.corpus_revision != project.corpus_revision:
            raise CorpusChanged(
                {"job_corpus_revision": job.corpus_revision,
                 "current": project.corpus_revision}
            )
        params = self._jobs.get_params(job.id)
        plan = self._plans.get_confirmed_plan_for_generation(
            job.project_id, params.get("plan_id"), job.corpus_revision
        )
        provider = self._provider
        if provider is None:
            raise ModelProtocolError("llm provider is not configured for generate stage")
        context = build_job_context(self._jobs, job.id, GENERATE_CALL_BUDGET)
        guard_active(context, "generate")
        try:
            return self._generate(job, project, plan, provider, context, params)
        finally:
            self._jobs.accumulate_llm_calls(job.id, context.budget.used)

    def _generate(self, job, project, plan, provider, context, params) -> JobResultRef:
        self._jobs.set_stage(job.id, "retrieving")
        guard_active(context, "generate")
        content_ver, content_body = load_system_prompt("content", self._prompts_dir)
        verify_ver, verify_body = load_system_prompt("verify", self._prompts_dir)
        audit_ver, audit_body = load_system_prompt("audit", self._prompts_dir)
        batches = [
            plan.slides[i : i + BATCH_SLIDES_MAX]
            for i in range(0, len(plan.slides), BATCH_SLIDES_MAX)
        ]
        claims: list[Claim] = []
        slides: list[Slide] = []
        claim_checks: list[ClaimVerification] = []
        unbound: list[UnboundAssertion] = []
        warnings: list[str] = []
        verdict_hashes: list[str] = []
        # 循环①（Q01/Q06）门：missing_evidence 非空=模型自认缺依据（P0 保守
        # blocked，放宽须先写 ADR）；可见文字审计覆盖不全=该批未审不得盖绿。
        missing_valid = True
        audit_valid = True
        block_refs_valid = True

        for batch in batches:
            hits_by_page = {
                i: search_chunks(
                    self._conn, project_id=job.project_id,
                    corpus_revision=job.corpus_revision,
                    query=f"{s.title} {s.purpose}", limit=TOP_K,
                )
                for i, s in enumerate(batch)
            }
            selected = select_evidence_within_budget(
                hits_by_page, per_key_max=PAGE_CHUNK_MAX, char_budget=BATCH_CHAR_BUDGET
            )
            messages = content_messages(
                project.course, batch, selected,
                system_body=content_body, system_ver=content_ver,
            )
            self._jobs.set_stage(job.id, "generating")
            guard_active(context, "generate")
            proposal = provider.complete_json(
                "generate_content", "ContentProposal", messages, context
            ).value
            located, failures, proposal, batch_slides, ref_failures = self._locate_batch(
                job, batch, selected, proposal, provider, context,
                content_body, content_ver,
            )
            # illustration 块引用定位失败（循环②Q04）：失败引用不得入库伪造来源，
            # 转换后 refs 为空+报告；任一失败即整候选不可提交（引用关系不完整）。
            if ref_failures:
                block_refs_valid = False
                warnings.extend(f"illustration 引用定位失败：{r}" for r in ref_failures)
            # 失败 claim 不进模型队列（locator 合法性由程序决定，verify.md）；
            # invalid 记录本身就是 blocked 的依据。
            for cid, reason in failures.items():
                claim_checks.append(
                    ClaimVerification(
                        claim_id=cid, locator_status="invalid",
                        semantic_status="not_checked", reason=reason[:600],
                    )
                )
            batch_verdicts = self._verify_batch(
                job, located, batch_slides, provider, context, verify_body, verify_ver
            )
            if batch_verdicts is not None:
                checks_map, dup_ids, batch_unbound, raw_sha, extra_ids = batch_verdicts
                verdict_hashes.append(raw_sha)
                unbound.extend(batch_unbound)
                claim_checks.extend(
                    verdicts_to_checks(located, checks_map, dup_ids, extra_ids)
                )
            # 独立可见文字审计（循环①Q01）：与 claim 语义核验分离，零 claim 批
            # 也必须过；豁免判据=教师计划 layout=title，模型自报 title 不算豁免。
            batch_audit = self._audit_batch(
                job, batch, batch_slides, located, provider, context, audit_body, audit_ver
            )
            if batch_audit is not None:
                audit_ok, batch_audit_unbound = batch_audit
                if not audit_ok:
                    audit_valid = False
                    warnings.append(
                        "可见文字审计未恰好覆盖本批必审页面（遗漏/重复/未知页均不采信）"
                    )
                unbound.extend(batch_audit_unbound)
            claims.extend(located)
            slides.extend(batch_slides)
            warnings.extend(proposal.missing_evidence)
            if proposal.missing_evidence:
                missing_valid = False

        relations_valid = self._relations_valid(slides, claims)
        # 确定性重排（循环③Q07）：页顺序是教师确认大纲的一部分。模型只是
        # 批内乱序返回时，服务器按计划顺序规范化落库——顺序差异不是内容差异，
        # 不得因此浪费一次模型调用，也不得让乱序候选进入教师视野。
        # id 集合不一致（增删/换页）由 layout 门拦截，保持原样供教师审阅。
        plan_layouts = {s.id: s.layout for s in plan.slides}
        if {s.id for s in slides} == set(plan_layouts) and len(slides) == len(plan.slides):
            # len 相等+集合相等才无重复 id；重复 id 时保留模型原样落库供教师
            # 审阅（layout/relations 门已拦），重排不去重、不静默丢页。
            by_id = {s.id: s for s in slides}
            slides = [by_id[ps.id] for ps in plan.slides]
        # layout 门（T09-Review N2 + 循环③Q07）：页数相等不够——生成页 id
        # 集合必须与教师确认计划完全一致（偷换/增删页不得过门），且每页
        # layout 不得被模型私自改变（布局是教师确认的教学设计的一部分）。
        layout_valid = (
            {s.id for s in slides} == {s.id for s in plan.slides}
            and len(slides) == len(plan.slides)
            and all(len(s.blocks) >= 1 for s in slides)
            and all(plan_layouts.get(s.id) == s.layout for s in slides)
        )
        # 可执行门（docs/04:41）：全部 claim 恰好覆盖一次、引用可解析、语义全
        # supported、关系/结构通过、unbound 为空——任一不满足即 blocked。
        covered = [x.claim_id for x in claim_checks]
        full_coverage = len(covered) == len(set(covered))
        can_commit = (
            relations_valid
            and layout_valid
            and full_coverage
            and missing_valid
            and audit_valid
            and block_refs_valid
            and all(x.semantic_status == "supported" for x in claim_checks)
            and not unbound
        )
        try:
            deck = DeckSpec(
                schema_version="1.0.0",
                project_id=job.project_id,
                # 候选拟议 version 只是占位事实；服务端提交时以 CAS 重算（docs/18:45）。
                version=int(params.get("base_version", 0)) + 1,
                corpus_revision=job.corpus_revision,
                course=project.course,
                claims=claims,
                slides=slides,
            )
        except ValidationError as exc:
            # 模型越界产出（跨批累加超 DeckSpec 上限）=不可信输出，typed 失败
            # 收口 job（T09-Review N3）；不得截断内容伪装 blocked，也不留 INTERNAL_ERROR。
            raise ModelOutputInvalid(
                "model output exceeds DeckSpec bounds",
                {"errors": str(exc)[:600]},
            ) from exc
        report = ValidationReport(
            schema_valid=True,
            relations_valid=relations_valid,
            layout_valid=layout_valid,
            claim_checks=claim_checks[:96],
            warnings=[w[:600] for w in warnings[:40]],
            can_commit=can_commit,
            model_id=self._model_id,
            prompt_version=f"{content_ver}+{verify_ver}+{audit_ver}",
            checked_at=_now_iso(),
            raw_result_sha256=canonical_sha(verdict_hashes) if verdict_hashes else None,
            unbound_assertions=unbound[:64],
        )
        change = CandidateChange(
            id=new_change_id(),
            project_id=job.project_id,
            base_version=int(params.get("base_version", 0)),
            corpus_revision=job.corpus_revision,
            status="ready" if can_commit else "blocked",
            kind="generation",
            affected_slide_ids=[s.id for s in slides],
            summary=self._summary(deck, report),
            candidate=deck,
            validation=report,
            created_at=_now_iso(),
        )
        # 写候选前复查执行有效性（循环④Q08）：取消/deadline/外部状态变化落在
        # "最后一次核验完成→写库"窗口内时不得留下可被应用的孤儿候选。
        guard_writable(self._jobs, job.id, context, "generate")
        self._changes.create(change)
        return JobResultRef(type="change", id=change.id)

    # ---------- locator + 一次修复 ----------

    def _locate_batch(self, job, batch, selected, proposal, provider, context,
                      content_body, content_ver):
        """ContentProposal → 存储 Claim + 存储 Slide；定位失败整批一次修复机会
        （docs/06:26）。引用允许集合=本批实际进 prompt 的片段（循环②Q05）——
        项目语料里存在但模型没见到的 chunk 同样不得引用。

        返回 (located, failures, final_proposal, batch_slides, ref_failures)——
        核验与落库必须使用与 located 同版本的最终 proposal（T09-Review B1：
        不得"核验A展示B"）；batch_slides 为服务器解析权威字段后的存储 Slide。
        """
        allowed = {hit.chunk_id for _, hit in selected}
        for attempt in (0, 1):
            located, failures = [], {}
            for cp in proposal.claims:
                spans, errs = [], []
                for ref in cp.evidence_refs:
                    try:
                        spans.append(
                            resolve_evidence(
                                self._conn, project_id=job.project_id,
                                corpus_revision=job.corpus_revision, proposal=ref,
                                allowed_chunk_ids=allowed,
                            )
                        )
                    except DomainError as exc:
                        errs.append(f"{ref.chunk_id}: {exc.message}")
                if spans and not errs:
                    located.append(
                        Claim(
                            id=cp.id, text=cp.text, kind=cp.kind,
                            evidence_refs=spans, rationale=cp.rationale,
                        )
                    )
                else:
                    failures[cp.id] = (
                        "; ".join(errs) if errs else "claim has no resolvable evidence refs"
                    )
            batch_slides, ref_failures = self._convert_slides(job, proposal, allowed)
            if (not failures and not ref_failures) or attempt == 1:
                return located, failures, proposal, batch_slides, ref_failures
            note = (
                "以下引用定位失败，quote 必须是本批允许片段的精确唯一原文子串；"
                "只修正引用（不改教师计划页与 claim 范围）："
                + json.dumps(
                    {"claims": failures, "illustration_refs": ref_failures},
                    ensure_ascii=False,
                )
            )
            messages = content_messages(
                self._projects.get(job.project_id).course, batch, selected,
                system_body=content_body, system_ver=content_ver,
                repair_note=note, prior=proposal,
            )
            proposal = provider.complete_json(
                "generate_content", "ContentProposal", messages, context
            ).value

    def _convert_slides(self, job, proposal, allowed):
        """提案 Slide → 存储 Slide（循环②Q04）：illustration 的 chunk_id+quote
        引用全部经服务器 locator 解析填充权威字段；解析失败的引用不入库
        （宁可空 refs+报告，绝不存可疑/伪造来源）。返回 (slides, ref_failures)。"""
        ref_failures: list[str] = []
        slides: list[Slide] = []
        for s in proposal.slides:
            blocks = []
            for b in s.blocks:
                if b.type == "illustration":
                    spans = []
                    for ref in b.evidence_refs:
                        try:
                            spans.append(
                                resolve_evidence(
                                    self._conn, project_id=job.project_id,
                                    corpus_revision=job.corpus_revision, proposal=ref,
                                    allowed_chunk_ids=allowed,
                                )
                            )
                        except DomainError as exc:
                            ref_failures.append(f"{ref.chunk_id}: {exc.message}")
                    blocks.append(
                        IllustrationBlock(
                            type="illustration", text=b.text,
                            assumptions=b.assumptions, evidence_refs=spans,
                        )
                    )
                else:
                    blocks.append(b)
            slides.append(
                Slide(id=s.id, title=s.title, layout=s.layout, blocks=blocks)
            )
        return slides, ref_failures

    # ---------- 语义核验 ----------

    def _verify_batch(self, job, located, batch_slides, provider, context, verify_body, verify_ver):
        """返回 (checks_map, dup_ids, unbound, raw_sha, extra_ids)；零 fact 批
        不调语义核验模型（docs/18:43）——但可见文字审计是独立通道，不受此限。"""
        if not located:
            return None
        self._jobs.set_stage(job.id, "validating")
        guard_active(context, "generate")
        messages = verify_messages(
            located, batch_slides, system_body=verify_body, system_ver=verify_ver
        )
        verdicts = provider.complete_json(
            "verify_claims", "SemanticVerdicts", messages, context
        ).value
        checks_map, duplicate_ids, extra_ids = map_verdicts(
            verdicts, {c.id for c in located}
        )
        raw_sha = canonical_sha(verdicts.model_dump(mode="json"))
        return checks_map, duplicate_ids, list(verdicts.unbound_assertions), raw_sha, extra_ids

    def _audit_batch(self, job, batch, batch_slides, located, provider, context,
                     audit_body, audit_ver):
        """独立可见文字审计（循环①Q01）：与 claim 核验分离的必过通道。

        豁免判据=教师计划页 layout=title（模型自报 layout 不算豁免）；
        服务端对 audited_slide_ids 与必审页集合做双射核验——遗漏/重复/未知
        ID 任一命中即整批审计无效（不得因模型少审而盖绿）。
        返回 None=本批全部为教师确认的封面页，合法豁免；否则 (ok, unbound)。
        """
        exempt = {s.id for s in batch if s.layout == "title"}
        required = [s.id for s in batch_slides if s.id not in exempt]
        if not required:
            return None
        self._jobs.set_stage(job.id, "validating")
        guard_active(context, "generate")
        messages = audit_messages(
            batch_slides, located, required,
            system_body=audit_body, system_ver=audit_ver,
        )
        audit = provider.complete_json(
            "audit_visible_text", "VisibleTextAudit", messages, context
        ).value
        audited = audit.audited_slide_ids
        ok = sorted(audited) == sorted(required)
        return ok, list(audit.unbound_assertions)

    # ---------- 结构与门 ----------

    @staticmethod
    def _relations_valid(slides, claims) -> bool:
        # T12：真值迁入 edit_patch.relations_valid，生成/编辑共用一份实现。
        return relations_valid(slides, claims)

    @staticmethod
    def _summary(deck: DeckSpec, report: ValidationReport) -> str:
        parts = [f"候选生成：{len(deck.slides)}页/{len(deck.claims)}claims"]
        invalid = [c for c in report.claim_checks if c.locator_status == "invalid"]
        unverified = [c for c in report.claim_checks if c.semantic_status != "supported"]
        if invalid:
            parts.append(f"{len(invalid)}条引用定位失败")
        if unverified:
            parts.append(f"{len(unverified)}条未通过语义核验")
        if report.warnings:
            parts.append(f"{len(report.warnings)}条缺证据说明")
        return "；".join(parts)[:2000]

    # ---------- 读取 ----------

    def get_change(self, project_id: str, change_id: str) -> CandidateChange:
        change = self._changes.get(change_id)
        # 跨项目按不存在处理：404 不泄露"该 id 在别的项目下存在"。
        if change is None or change.project_id != project_id:
            raise ChangeNotFound({"change_id": change_id})
        project = self._projects.get(project_id)
        if project is None:
            raise ProjectNotFound({"project_id": project_id})
        return self._with_stale(change, project)

    @staticmethod
    def _with_stale(change: CandidateChange, project) -> CandidateChange:
        """stale 只在读路径计算（与 plans 同语义，从不写库）：ready/blocked
        候选的基线一旦落后（版本被他人提交/语料前进）即不可再应用。
        committed/discarded 是历史事实，不随基线漂移。"""
        if change.status in ("ready", "blocked") and (
            change.base_version != project.current_version
            or change.corpus_revision != project.corpus_revision
        ):
            return change.model_copy(update={"status": "stale"})
        return change

    # ---------- 提交（生成与应用分离的"应用"侧） ----------

    def commit_change(
        self, project_id: str, change_id: str, request: CommitRequest
    ) -> DeckVersion:
        change = self.get_change(project_id, change_id)
        project = self._projects.get(project_id)
        if change.status == "stale":
            # 过期要报根因（教师下一步动作不同）：补材料→重新生成；
            # 版本被推进→刷新视图后对新候选再确认。
            if change.corpus_revision != project.corpus_revision:
                raise CorpusChanged(
                    {"change_corpus": change.corpus_revision,
                     "current": project.corpus_revision}
                )
            raise VersionConflict(
                {"change_base": change.base_version,
                 "current": project.current_version}
            )
        if change.status != "ready" or not change.validation.can_commit:
            # blocked/committed/can_commit=false 一律拒绝：未经支持的
            # 内容不得被一次点击盖绿（docs/04:41）。
            raise ChangeNotCommittable(
                {"change_id": change_id, "status": change.status,
                 "can_commit": change.validation.can_commit}
            )
        if (request.base_version != change.base_version
                or request.corpus_revision != change.corpus_revision):
            raise VersionConflict(
                {
                    "request_base": request.base_version,
                    "change_base": change.base_version,
                    "request_corpus": request.corpus_revision,
                    "change_corpus": change.corpus_revision,
                }
            )

        def _mark(conn: sqlite3.Connection) -> None:
            if not self._changes.mark_committed_tx(conn, change_id, _now_iso()):
                # 指针 CAS 已过但候选态被并发改写：回滚整个提交。
                raise VersionConflict({"change_id": change_id, "reason": "already committed"})

        return self._versions.commit_version(
            project_id,
            change.candidate,
            expected_base_version=change.base_version,
            expected_corpus_revision=change.corpus_revision,
            on_committed=_mark,
        )
