"""T12：编辑服务——受理门、确定性 reorder 执行、模型意图路径（loop④接入）。

受理期只做无需模型即可判定的门（负责人拍板）：项目/版本/语料/目标页存在性、
结构化指令语法；自由文本的意图判定属模型路径，不支持时 job=failed
EDIT_UNSUPPORTED，资料不足 job=blocked，与模型错误三类不混淆（api.md:59）。
"""

import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from courseware_core.errors import (
    ConsentRequired,
    CorpusChanged,
    DeckNotFound,
    DomainError,
    EditUnsupported,
    InsufficientEvidence,
    JobCancelled,
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
    DeckPatch,
    EditProposal,
    EditRequest,
    Job,
    JobAccepted,
    JobResultRef,
    UnboundAssertion,
    ValidationReport,
)
from courseware_core.retrieval.bm25 import search_chunks
from courseware_core.retrieval.context import select_evidence_within_budget
from courseware_core.services.claim_verdicts import map_verdicts, verdicts_to_checks
from courseware_core.services.coverage_service import TOP_K
from courseware_core.services.edit_messages import edit_messages
from courseware_core.services.edit_patch import apply_patch, moved_slide_ids, relations_valid
from courseware_core.services.generate_messages import verify_messages
from courseware_core.services.generate_service import (
    BATCH_CHAR_BUDGET,
    PAGE_CHUNK_MAX,
    GenerateService,
    canonical_sha,
    new_change_id,
)
from courseware_core.services.idempotency_service import OperationBinder
from courseware_core.storage.change_repository import ChangeRepository
from courseware_core.storage.job_repository import JobRepository
from courseware_core.storage.project_repository import ProjectRepository
from courseware_core.storage.version_repository import VersionRepository

DETERMINISTIC_PROMPT_VERSION = "deterministic-reorder-v1"
# 预算按"实际 HTTP 请求"计（adapter._send 扣减）：propose+locator 修复+verify
# 最多 3 次逻辑调用，每次最坏 1 初始+1 网络重试+1 格式修复=3 → 9。
EDIT_CALL_BUDGET = 9


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_deterministic_instruction(
    instruction: str, deck_slide_ids: list[str]
) -> Optional[list[dict]]:
    """结构化指令：JSON 对象且含 action 字段才进入确定性路径。

    不匹配该语法的输入一律视为自由文本（返回 None 走模型），不做词面猜测；
    匹配了 action 但语义非法（未知 action、非全量置换）是"可判定的不支持"，
    直接 EditUnsupported——教师拿到的反馈比模型转述更快也更准。
    """
    try:
        parsed = json.loads(instruction)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict) or "action" not in parsed:
        return None
    action = parsed.get("action")
    if action != "reorder":
        raise EditUnsupported(
            "structured edit action is not supported", {"action": action}
        )
    slide_ids = parsed.get("slide_ids")
    if not isinstance(slide_ids, list) or sorted(slide_ids) != sorted(deck_slide_ids):
        raise EditUnsupported(
            "reorder must list every current slide exactly once",
            {"slide_ids": slide_ids},
        )
    return [{"op": "reorder_slides", "slide_ids": slide_ids}]


class EditService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        provider=None,
        prompts_dir: Optional[Path] = None,
        model_id: Optional[str] = None,
        provider_factory=None,
    ):
        self._conn = conn
        self._provider = provider
        # provider_factory=() -> (provider, model_id)：worker 装配层惰性解析真实
        # adapter，确定性路径永不触发（无 APP_LLM_* 也必须能跑 reorder）。
        self._provider_factory = provider_factory
        self._prompts_dir = prompts_dir
        self._model_id = model_id
        self._changes = ChangeRepository(conn)
        self._jobs = JobRepository(conn)
        self._projects = ProjectRepository(conn)
        self._versions = VersionRepository(conn)
        # 候选读取/陈旧标记只有一份实现（T09），编辑候选与生成候选同表同语义。
        self._reader = GenerateService(conn)

    # ---------- 受理 ----------

    def create_edit_job(
        self,
        project_id: str,
        request: EditRequest,
        request_id: Optional[str] = None,
        binder: Optional[OperationBinder] = None,
    ) -> JobAccepted:
        project = self._projects.get(project_id)
        if project is None:
            raise ProjectNotFound({"project_id": project_id})
        if request.base_version != project.current_version:
            raise VersionConflict(
                {"requested": request.base_version, "current": project.current_version}
            )
        if request.corpus_revision != project.corpus_revision:
            raise CorpusChanged(
                {"requested": request.corpus_revision, "current": project.corpus_revision}
            )
        deck = self._versions.get_deck(project_id, project.current_version)
        if deck is None:
            raise DeckNotFound(
                {"project_id": project_id, "version": project.current_version}
            )
        deck_slide_ids = [s.id for s in deck.slides]
        unknown = [t for t in request.target_slide_ids if t not in deck_slide_ids]
        if unknown:
            raise EditUnsupported(
                "target slides do not exist in the base deck",
                {"unknown_slide_ids": unknown},
            )
        operations = parse_deterministic_instruction(request.instruction, deck_slide_ids)
        if operations is None:
            # 自由文本=模型意图路径，必然外发推理：先过云处理告知门。
            if not project.consent_to_cloud_processing:
                raise ConsentRequired({"project_id": project_id})
            params = {
                "mode": "model",
                "instruction": request.instruction,
                "target_slide_ids": request.target_slide_ids,
                "base_version": request.base_version,
            }
        else:
            # 确定性 reorder 不外发任何内容（PRD:19 排序不耗模型），不设告知门。
            params = {
                "mode": "deterministic",
                "operations": operations,
                "target_slide_ids": request.target_slide_ids,
                "base_version": request.base_version,
            }
        job_id = f"job_{secrets.token_hex(16)}"
        anchor = (lambda conn: binder.bind(job_id)) if binder is not None else None
        self._changes.create_write_job(
            project_id,
            kind="edit",
            job_id=job_id,
            corpus_revision=request.corpus_revision,
            params_json=json.dumps(params, ensure_ascii=False),
            request_id=request_id,
            on_committed=anchor,
        )
        return JobAccepted(job_id=job_id)

    # ---------- worker 执行 ----------

    def handle_edit(self, job: Job) -> JobResultRef:
        project = self._projects.get(job.project_id)
        if project is None:
            raise ProjectNotFound({"project_id": job.project_id})
        if job.corpus_revision != project.corpus_revision:
            raise CorpusChanged(
                {"job_corpus_revision": job.corpus_revision,
                 "current": project.corpus_revision}
            )
        if job.base_version != project.current_version:
            raise VersionConflict(
                {"job_base_version": job.base_version,
                 "current": project.current_version}
            )
        params = self._jobs.get_params(job.id)
        deck = self._versions.get_deck(job.project_id, job.base_version)
        if deck is None:
            raise DeckNotFound({"project_id": job.project_id, "version": job.base_version})
        if params.get("mode") == "deterministic":
            return self._apply_deterministic(job, params, deck)
        return self._model_edit(job, project, params, deck)

    def _apply_deterministic(self, job: Job, params: dict, deck) -> JobResultRef:
        self._jobs.set_stage(job.id, "validating")
        patch = DeckPatch(
            base_version=deck.version,
            corpus_revision=deck.corpus_revision,
            operations=params["operations"],
            claims=[],
            summary="确定性重排：按教师结构化指令调整页面顺序，未改动任何页内容。",
        )
        result = apply_patch(
            deck, patch, authorized_slide_ids=params["target_slide_ids"]
        )
        affected = moved_slide_ids(deck.slides, result.slides)
        return self._emit_candidate(
            job, params, result, patch.summary, affected, layout_valid=True
        )

    def _model_edit(self, job: Job, project, params: dict, deck) -> JobResultRef:
        provider, model_id = self._resolve_provider()
        context = build_job_context(self._jobs, job.id, EDIT_CALL_BUDGET)
        guard_active(context, "edit")
        try:
            return self._run_model_edit(job, project, params, deck, provider, model_id, context)
        finally:
            self._jobs.accumulate_llm_calls(job.id, context.budget.used)

    def _resolve_provider(self):
        if self._provider is not None:
            return self._provider, self._model_id
        if self._provider_factory is not None:
            return self._provider_factory()
        raise ModelProtocolError("llm provider is not configured for edit stage")

    def _run_model_edit(self, job, project, params, deck, provider, model_id, context):
        targets = list(params["target_slide_ids"])
        target_slides = [s for s in deck.slides if s.id in targets]
        referenced = {
            b.claim_id for s in target_slides for b in s.blocks if b.type == "fact"
        }
        existing_claims = [c for c in deck.claims if c.id in referenced]
        hits_by_key = {
            s.id: search_chunks(
                self._conn, project_id=job.project_id,
                corpus_revision=job.corpus_revision,
                query=f"{params['instruction']} {s.title}", limit=TOP_K,
            )
            for s in target_slides
        }
        selected = select_evidence_within_budget(
            hits_by_key, per_key_max=PAGE_CHUNK_MAX, char_budget=BATCH_CHAR_BUDGET
        )
        allowed = {hit.chunk_id for _, hit in selected}
        edit_ver, edit_body = load_system_prompt("edit", self._prompts_dir)
        self._jobs.set_stage(job.id, "generating")
        guard_active(context, "edit")
        proposal = self._propose(
            job, provider, context,
            edit_messages(
                project.course, params["instruction"], targets, target_slides,
                existing_claims, deck.slides, selected,
                system_body=edit_body, system_ver=edit_ver,
            ),
        )
        # locator 门（T09 同规则）：引用定位失败一次修复机会；修复后仍失败
        # 的 claim 丢弃（不进语义队列、不伪造来源）→ 悬空引用由 relations
        # 门自然拦成 blocked。
        failures: dict[str, str] = {}
        located: list[Claim] = []
        for attempt in (0, 1):
            located, failures = self._resolve_patch_claims(job, proposal, allowed, deck)
            if not failures or attempt == 1:
                break
            note = (
                "以下引用定位失败，quote 必须是允许片段的精确唯一原文子串；"
                "只修正引用（不改操作范围与页面结构）："
                + json.dumps(failures, ensure_ascii=False)
            )
            proposal = self._propose(
                job, provider, context,
                edit_messages(
                    project.course, params["instruction"], targets, target_slides,
                    existing_claims, deck.slides, selected,
                    system_body=edit_body, system_ver=edit_ver,
                    repair_note=note, prior=proposal,
                ),
            )
        patch = DeckPatch(
            base_version=deck.version,
            corpus_revision=deck.corpus_revision,
            operations=proposal.operations,
            claims=located,
            summary=proposal.summary,
        )
        result = apply_patch(deck, patch, authorized_slide_ids=targets)

        deck_claim_ids = {c.id for c in deck.claims}
        new_claims = [c for c in located if c.id not in deck_claim_ids]
        deck_ids = {s.id for s in deck.slides}
        created_ids = [s.id for s in result.slides if s.id not in deck_ids]
        before_dump = {s.id: s.model_dump(mode="json") for s in deck.slides}
        changed = [
            s.id for s in result.slides
            if s.id in targets and s.model_dump(mode="json") != before_dump.get(s.id)
        ]
        # N-1：模型产出 reorder 只改顺序不改内容——affected 并入位置比较，
        # 与确定性路径同口径，不得恒为空误导教师审阅。
        affected = changed + created_ids + [
            mid for mid in moved_slide_ids(deck.slides, result.slides)
            if mid not in changed and mid not in created_ids
        ]

        checks: list[ClaimVerification] = []
        unbound: list[UnboundAssertion] = []
        raw_sha: str | None = None
        verify_ver = ""
        if new_claims:
            verify_ver, verify_body = load_system_prompt("verify", self._prompts_dir)
            self._jobs.set_stage(job.id, "validating")
            guard_active(context, "edit")
            affected_slides = [s for s in result.slides if s.id in set(affected)]
            verdicts = provider.complete_json(
                "verify_claims", "SemanticVerdicts",
                verify_messages(
                    new_claims, affected_slides,
                    system_body=verify_body, system_ver=verify_ver,
                ),
                context,
            ).value
            checks_map, dup_ids, extra_ids = map_verdicts(
                verdicts, {c.id for c in new_claims}
            )
            checks = verdicts_to_checks(new_claims, checks_map, dup_ids, extra_ids)
            unbound = list(verdicts.unbound_assertions)
            raw_sha = canonical_sha(verdicts.model_dump(mode="json"))
        for cid, reason in failures.items():
            checks.append(
                ClaimVerification(
                    claim_id=cid, locator_status="invalid",
                    semantic_status="not_checked", reason=reason[:600],
                )
            )

        rel = relations_valid(result.slides, result.claims)
        expected_count = len(deck.slides) + sum(
            1 for op in patch.operations if op.op == "split_slide"
        )
        layout_ok = len(result.slides) == expected_count and all(
            len(s.blocks) >= 1 for s in result.slides
        )
        all_supported = all(
            c.locator_status == "located" and c.semantic_status == "supported"
            for c in checks
        )
        can_commit = rel and layout_ok and all_supported and not unbound
        warnings = []
        if failures:
            warnings.extend(f"claim 引用定位失败：{cid}" for cid in failures)
        if unbound:
            warnings.append("编辑页存在无证据绑定的专业断言")
        warnings.append(
            f"本次新增核验 {len(new_claims)} 条；未变更的既有 claim 沿用生成时核验，未重烧模型"
        )
        report = ValidationReport(
            schema_valid=True,
            relations_valid=rel,
            layout_valid=layout_ok,
            claim_checks=checks[:96],
            warnings=[w[:600] for w in warnings[:40]],
            can_commit=can_commit,
            model_id=model_id,
            prompt_version=f"{edit_ver}+{verify_ver}" if verify_ver else edit_ver,
            checked_at=_now_iso(),
            raw_result_sha256=raw_sha,
            unbound_assertions=unbound[:64],
        )
        change = CandidateChange(
            id=new_change_id(),
            project_id=job.project_id,
            base_version=job.base_version,
            corpus_revision=job.corpus_revision,
            status="ready" if can_commit else "blocked",
            kind="edit",
            affected_slide_ids=affected,
            summary=patch.summary,
            candidate=result,
            validation=report,
            created_at=_now_iso(),
        )
        # B-1（Q08 同规则）：取消/deadline 落在"最后一次核验完成→写库"窗口
        # 内时不得留下可被 GET/commit 的 ready 孤儿候选。
        guard_writable(self._jobs, job.id, context, "edit")
        self._changes.create(change)
        return JobResultRef(type="change", id=change.id)

    def _propose(self, job, provider, context, messages) -> EditProposal:
        decision = provider.complete_json(
            "edit_propose", "EditDecision", messages, context
        ).value
        if decision.decision == "unsupported":
            raise EditUnsupported(
                "model declined the edit intent", {"reason": decision.reason}
            )
        if decision.proposal.missing_evidence:
            # 模型自认缺依据：blocked+INSUFFICIENT_EVIDENCE，与 failed 严格分流
            # （api.md:59）；不留"半套候选"，教师补材料后重新发起。
            raise InsufficientEvidence(
                "edit requires evidence not present in materials",
                {"missing_evidence": [
                    m.model_dump(mode="json") if hasattr(m, "model_dump") else str(m)
                    for m in decision.proposal.missing_evidence
                ][:16]},
            )
        return decision.proposal

    def _resolve_patch_claims(self, job, proposal, allowed: set[str], deck):
        located: list[Claim] = []
        failures: dict[str, str] = {}
        existing_by_id = {c.id: c for c in deck.claims}
        for cp in proposal.claims:
            existing = existing_by_id.get(cp.id)
            if (
                existing is not None
                and cp.text == existing.text
                and cp.kind == existing.kind
            ):
                # 权威复用（api.md:57）：未变更的既有 claim 直接沿用服务器
                # 存储版 span；其证据 chunk 不在本批允许集合是正常现象，
                # 不得误判为 locator 失败把合法编辑拦成假 blocked（N-2）。
                continue
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
        return located, failures

    def _emit_candidate(
        self, job: Job, params: dict, deck, summary: str, affected: list[str],
        *, layout_valid: bool,
    ) -> JobResultRef:
        rel = relations_valid(deck.slides, deck.claims)
        report = ValidationReport(
            schema_valid=True,
            relations_valid=rel,
            layout_valid=layout_valid,
            claim_checks=[],
            warnings=[],
            can_commit=rel,
            model_id=None,
            prompt_version=DETERMINISTIC_PROMPT_VERSION,
            checked_at=_now_iso(),
            raw_result_sha256=None,
            unbound_assertions=[],
        )
        change = CandidateChange(
            id=new_change_id(),
            project_id=job.project_id,
            base_version=job.base_version,
            corpus_revision=job.corpus_revision,
            status="ready" if report.can_commit else "blocked",
            kind="edit",
            affected_slide_ids=affected,
            summary=summary,
            candidate=deck,
            validation=report,
            created_at=_now_iso(),
        )
        # B-1（Q08 同规则）：取消落在"受理→执行"窗口内不得留 ready 孤儿
        # 候选——写库前按 DB 实况复查 running+未取消。deadline 不在这里查：
        # deadline 是模型成本预算语义（execution_guard 定位），确定性路径
        # 零模型调用无成本可保护，版本一致性由 handle_edit 入口 CAS 复查兜底。
        current = self._jobs.get_execution_state(job.id)
        if (
            current is None
            or current["status"] != "running"
            or current["cancel_requested"]
        ):
            raise JobCancelled(
                {"stage": "edit", "reason": "execution invalid before result write"}
            )
        self._changes.create(change)
        return JobResultRef(type="change", id=change.id)

    # ---------- 读取（与生成候选同一实现） ----------

    def get_change(self, project_id: str, change_id: str) -> CandidateChange:
        return self._reader.get_change(project_id, change_id)
