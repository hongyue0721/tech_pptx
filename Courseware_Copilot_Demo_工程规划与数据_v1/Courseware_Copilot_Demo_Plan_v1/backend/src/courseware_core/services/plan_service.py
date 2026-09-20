"""T08 大纲生成与教师确认：Planner.create/confirm（docs/18）。

- create：worker plan handler 内执行——逐目标coverage（服务端计算，真源）+
  按 docs/05 裁剪证据上下文 → adapter 产出 PlanProposal → 服务端组装
  LessonPlan（draft/needs_material），停在教师确认，绝不自行 confirmed。
- confirm：教师调整 slides/接受范围后服务端重检引用与 coverage；
  缺口目标必须被明确移出接受范围（不假绿）；语料前进即 stale 拒确认。
- 全目标无支持 → InsufficientEvidence（job blocked，不烧模型调用）。
- 云推理入口受 consent 门禁：consent=false 时受理拒绝、执行复核拒绝，
  任何路径零 provider 调用（api.md §创建与资料、docs/11 云处理）。
- 系统提示词唯一事实源 = app-prompts/plan.md（llm/prompts.py 加载，带版本）。
"""

import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from courseware_core.errors import (
    ConsentRequired,
    CorpusChanged,
    InsufficientEvidence,
    ModelProtocolError,
    PlanNotConfirmed,
    PlanNotFound,
    ProjectNotFound,
    ValidationFailed,
)
from courseware_core.jobs.execution_guard import build_job_context, guard_active
from courseware_core.llm.prompts import load_system_prompt
from courseware_core.models import (
    ConfirmPlanRequest,
    Job,
    JobAccepted,
    JobResultRef,
    LessonPlan,
    PlanProposal,
    PlanRequest,
)
from courseware_core.retrieval.bm25 import search_chunks
from courseware_core.retrieval.context import select_evidence_within_budget
from courseware_core.services.coverage_service import (
    TOP_K,
    evaluate_goal_coverage,
)
from courseware_core.services.idempotency_service import OperationBinder
from courseware_core.storage.job_repository import JobRepository
from courseware_core.storage.plan_repository import PlanRepository, new_plan_id
from courseware_core.storage.project_repository import ProjectRepository

# 上下文预算（docs/05 §9）：去重后每目标最多8片段、总正文约8000字符。
# 换供应商/更大规模需重估时改这里并同步文档，不散落魔法数。
CONTEXT_PER_GOAL_MAX = 8
CONTEXT_CHAR_BUDGET = 8000

# plan 单次逻辑调用的HTTP上限：1原始+1修复+退避重试余量（docs/06 重试矩阵）。
PLAN_CALL_BUDGET = 4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PlanService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        provider=None,
        prompts_dir: Optional[Path] = None,
    ):
        self._conn = conn
        self._provider = provider
        # None → llm.prompts 按 APP_PROMPTS_DIR/内置默认解析（唯一事实源位置）。
        self._prompts_dir = prompts_dir
        self._plans = PlanRepository(conn)
        self._projects = ProjectRepository(conn)
        self._jobs = JobRepository(conn)

    # ---------- 受理 ----------

    def create_plan_job(
        self,
        project_id: str,
        request: PlanRequest,
        request_id: Optional[str] = None,
        binder: Optional[OperationBinder] = None,
    ) -> JobAccepted:
        project = self._projects.get(project_id)
        if project is None:
            raise ProjectNotFound({"project_id": project_id})
        # 云推理受理门禁：告知未确认的项目不得进入任何外发推理（api.md §创建与资料）。
        # 本地解析路径不经过这里，天然不受影响。
        self._require_cloud_consent(project)
        # 请求必须绑定当前语料快照；过期视图或超前视图都拒绝（api.md：绑定corpus_revision）。
        if request.corpus_revision != project.corpus_revision:
            raise CorpusChanged(
                {
                    "requested": request.corpus_revision,
                    "current": project.corpus_revision,
                }
            )
        job_id = f"job_{secrets.token_hex(16)}"
        # R00-D 锚点：幂等占位行的 operation_ref 与 job 行同一事务提交，
        # "响应缓存未写就崩溃"后同键重试可凭锚点找回本 job。
        anchor = (lambda conn: binder.bind(job_id)) if binder is not None else None
        self._plans.create_with_job(
            project_id, job_id=job_id, corpus_revision=request.corpus_revision,
            request_id=request_id, on_committed=anchor,
        )
        return JobAccepted(job_id=job_id)

    @staticmethod
    def _require_cloud_consent(project) -> None:
        if not project.consent_to_cloud_processing:
            raise ConsentRequired({"project_id": project.id})

    # ---------- worker 执行 ----------

    def handle_plan(self, job: Job) -> JobResultRef:
        project = self._projects.get(job.project_id)
        if project is None:
            raise ProjectNotFound({"project_id": job.project_id})
        # 防御性复核（纵深）：受理路径已拦，旧队列/旁路进来的 job 也要在
        # 任何模型调用之前拒绝——consent=false 时 provider 零调用是硬约束。
        self._require_cloud_consent(project)
        # 防御性复核：写锁保证执行期语料不变，若不变式被破坏宁可失败也不混语料。
        if job.corpus_revision != project.corpus_revision:
            raise CorpusChanged(
                {
                    "job_corpus_revision": job.corpus_revision,
                    "current": project.corpus_revision,
                }
            )
        # R00-D：真实执行状态——总 deadline/取消从受理事实源（jobs 行）构建，
        # 昂贵动作（检索后的模型调用、入库）之前逐项收口，stage 随进度上报。
        context = build_job_context(self._jobs, job.id, PLAN_CALL_BUDGET)
        guard_active(context, "plan")
        goals = project.course.goals
        self._jobs.set_stage(job.id, "retrieving")
        coverage = evaluate_goal_coverage(
            self._conn, project_id=job.project_id, goals=goals
        )
        gap_goals = [c.goal_index for c in coverage if c.status == "unsupported"]
        if len(gap_goals) == len(goals):
            # 全部目标无材料支持：大纲无从谈起。blocked，不先花模型调用。
            raise InsufficientEvidence(
                "materials do not support any teaching goal",
                {"gap_goals": gap_goals},
            )

        hits_by_goal = {
            i: search_chunks(
                self._conn,
                project_id=job.project_id,
                corpus_revision=job.corpus_revision,
                query=goal,
                limit=TOP_K,
            )
            for i, goal in enumerate(goals)
        }
        # grounding 真源=实际进 prompt 的裁剪子集（N2）：命中但被8000字符预算
        # 裁掉的片段模型根本没见过，引用它同样是无依据输出。
        selected = self._assemble_context(hits_by_goal)
        # 系统提示词唯一事实源=app-prompts/plan.md（版本随文件头声明）；
        # 缺失即部署配置错误，显式失败且不烧模型调用。
        prompt_version, prompt_body = load_system_prompt("plan", self._prompts_dir)
        system_prompt = f"[prompt_version={prompt_version}]\n{prompt_body}"
        messages = self._build_messages(project, coverage, selected, system_prompt)

        provider = self._provider
        if provider is None:
            raise ModelProtocolError("llm provider is not configured for plan stage")
        self._jobs.set_stage(job.id, "planning")
        guard_active(context, "plan")
        try:
            completion = provider.complete_json(
                "plan_course", "PlanProposal", messages, context
            )
        finally:
            # 费用记账不依赖成功路径（N4）：失败/取消时按已消耗请求数如实累计，
            # budget.used 就是实际HTTP请求数（含重试与修复）。
            self._accumulate_llm_calls(job.id, context.budget.used)
        proposal: PlanProposal = completion.value

        self._require_unique_slide_ids(proposal.slides)
        permitted = {hit.chunk_id for _, hit in selected}
        for slide in proposal.slides:
            unknown = set(slide.evidence_chunk_ids) - permitted
            if unknown:
                # 模型引用了未提供/不属于本项目的片段：不可信输出，拒绝。
                raise ValidationFailed(
                    "plan slides reference unknown chunks",
                    {"slide_id": slide.id, "unknown_chunk_ids": sorted(unknown)},
                )
            self._require_evidence_on_content_slide(slide)
        # 有效目标必须被内容页覆盖（R00-C）："整份只有封面却宣称覆盖"的
        # 提案不可用，拒绝重跑，不让封面冒充教学内容的覆盖。
        self._require_valid_goals_covered(proposal.slides, coverage)

        has_gap = any(c.status in ("unsupported", "conflict") for c in coverage)
        self._jobs.set_stage(job.id, "validating")
        plan = LessonPlan(
            id=new_plan_id(),
            project_id=job.project_id,
            corpus_revision=job.corpus_revision,
            # 模型只提案 slides/coverage_notes；status、coverage、id 等由服务端决定
            # （docs/18：不让模型填它不应决定的状态）。
            status="needs_material" if has_gap else "draft",
            coverage=coverage,
            slides=proposal.slides,
            accepted_goal_indices=[
                c.goal_index for c in coverage if c.status in ("supported", "partial")
            ],
            created_at=_now_iso(),
        )
        self._plans.insert(plan)
        return JobResultRef(type="plan", id=plan.id)

    def _accumulate_llm_calls(self, job_id: str, attempts: int) -> None:
        self._jobs.accumulate_llm_calls(job_id, attempts)

    def _build_messages(self, project, coverage, selected, system_prompt: str) -> list:
        """组装 teacher_request + allowed_materials 两分区 user 消息（docs/05、app-prompts README）。

        有效目标/缺口由服务端 coverage 真源逐条标注——模型不应自己猜哪些目标无支持；
        允许引用集合显式列出=实际进 prompt 的裁剪子集，与 grounding 校验同一口径。
        """
        status_by_goal = {c.goal_index: c.status for c in coverage}
        lines = [
            "【教师请求】",
            f"课题：{project.course.topic}",
            f"对象：{project.course.audience}；时长：{project.course.duration_minutes}分钟",
            f"目标页数：{project.course.target_slides}",
            "教学目标：",
        ]
        for i, goal in enumerate(project.course.goals):
            if status_by_goal.get(i) in ("supported", "partial"):
                lines.append(f"{i}. {goal}（有效目标：有教材支持）")
            else:
                lines.append(
                    f"{i}. {goal}（缺口：当前材料未找到支持，不要安排页面）"
                )
        permitted_ids = sorted({hit.chunk_id for _, hit in selected})
        lines.append("【允许教材片段】")
        lines.append(f"只能引用以下片段编号：{'、'.join(permitted_ids)}")
        for goal_index, hit in selected:
            lines.append(
                f"【片段 {hit.chunk_id}｜文档 {hit.document_id}｜"
                f"目标{goal_index}｜第{hit.pdf_page}页】{hit.text}"
            )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "\n".join(lines)},
        ]

    def _assemble_context(self, hits_by_goal: dict):
        """按目标轮转取片段：每目标≤8、全局≤8000字符（docs/05 §9）。
        公平算法唯一实现在 retrieval/context（plan/generate 共用，不平行复制）。"""
        return select_evidence_within_budget(
            hits_by_goal,
            per_key_max=CONTEXT_PER_GOAL_MAX,
            char_budget=CONTEXT_CHAR_BUDGET,
        )

    # ---------- 读取（stale 在读取路径计算，不写库） ----------

    def get_plan(self, project_id: str, plan_id: str) -> LessonPlan:
        plan = self._plans.get(plan_id)
        if plan is None or plan.project_id != project_id:
            raise PlanNotFound({"plan_id": plan_id})
        project = self._projects.get(project_id)
        if project is None:
            raise ProjectNotFound({"project_id": project_id})
        return self._with_stale(plan, project.corpus_revision)

    @staticmethod
    def _with_stale(plan: LessonPlan, current_corpus_revision: int) -> LessonPlan:
        # 语料前进→旧计划过期（docs/07 §21）；读取时计算，避免材料入库路径反向耦合。
        if plan.corpus_revision < current_corpus_revision and plan.status != "stale":
            return plan.model_copy(update={"status": "stale"})
        return plan

    # ---------- 教师确认 ----------

    def confirm_plan(
        self, project_id: str, plan_id: str, request: ConfirmPlanRequest
    ) -> LessonPlan:
        plan = self._plans.get(plan_id)
        if plan is None or plan.project_id != project_id:
            raise PlanNotFound({"plan_id": plan_id})
        project = self._projects.get(project_id)
        if project is None:
            raise ProjectNotFound({"project_id": project_id})

        if plan.corpus_revision < project.corpus_revision:
            raise CorpusChanged(
                {
                    "plan_corpus_revision": plan.corpus_revision,
                    "current": project.corpus_revision,
                }
            )
        if request.corpus_revision != plan.corpus_revision:
            raise CorpusChanged(
                {
                    "requested": request.corpus_revision,
                    "plan_corpus_revision": plan.corpus_revision,
                }
            )
        if plan.status == "confirmed":
            # 幂等重放只认同载荷（N5）：已确认计划+不同 slides/范围 是矛盾请求，
            # 静默返回旧计划会掩盖教师意图丢失，须显式拒绝（要改范围走重新规划）。
            if (
                request.slides == plan.slides
                and request.accepted_goal_indices == plan.accepted_goal_indices
            ):
                return plan
            raise ValidationFailed(
                "plan already confirmed with different content; re-plan to change scope",
                {"plan_id": plan_id},
            )

        coverage_by_goal = {c.goal_index: c for c in plan.coverage}
        unknown_goals = [
            g for g in request.accepted_goal_indices if g not in coverage_by_goal
        ]
        if unknown_goals:
            raise ValidationFailed(
                "accepted goals not covered by this plan",
                {"unknown_goal_indices": unknown_goals},
            )
        gap_goals = [
            g
            for g in request.accepted_goal_indices
            if coverage_by_goal[g].status in ("unsupported", "conflict")
        ]
        if gap_goals:
            # 缺口目标必须被明确移出接受范围，不能点一次确认就盖绿章（docs/04）。
            raise ValidationFailed(
                "unsupported goals cannot be accepted; remove them or add materials",
                {"gap_goals": gap_goals},
            )

        accepted = set(request.accepted_goal_indices)
        self._require_unique_slide_ids(request.slides)
        permitted_chunks = self._permitted_chunk_ids(project_id)
        for slide in request.slides:
            outside = set(slide.goal_indices) - accepted
            if outside:
                raise ValidationFailed(
                    "slides must not touch goals outside accepted range",
                    {"slide_id": slide.id, "outside_goal_indices": sorted(outside)},
                )
            unknown = set(slide.evidence_chunk_ids) - permitted_chunks
            if unknown:
                raise ValidationFailed(
                    "slides reference chunks not in the project corpus",
                    {"slide_id": slide.id, "unknown_chunk_ids": sorted(unknown)},
                )
            self._require_evidence_on_content_slide(slide)
        # 接受的目标必须由至少一个内容页承载（R00-C）：
        # 只有封面页挂 goal_indices 不能代表覆盖，教师确认不得假绿。
        uncovered = sorted(accepted - self._content_covered_goals(request.slides))
        if uncovered:
            raise ValidationFailed(
                "accepted goals must each be covered by at least one content slide",
                {"uncovered_goal_indices": uncovered},
            )

        confirmed = plan.model_copy(
            update={
                "status": "confirmed",
                "slides": request.slides,
                "accepted_goal_indices": request.accepted_goal_indices,
            }
        )
        if not self._plans.confirm_cas(confirmed):
            # 并发窗口（不同幂等键同时通过上方校验）：他人已先确认。
            # 后写不得覆盖先写（R00-C）——重读按幂等语义裁决：同载荷=重放，
            # 异载荷=矛盾请求显式拒绝。
            fresh = self._plans.get(plan_id)
            if (
                fresh is not None
                and fresh.status == "confirmed"
                and request.slides == fresh.slides
                and request.accepted_goal_indices == fresh.accepted_goal_indices
            ):
                return fresh
            raise ValidationFailed(
                "plan already confirmed with different content; re-plan to change scope",
                {"plan_id": plan_id},
            )
        return confirmed

    def _permitted_chunk_ids(self, project_id: str) -> set:
        rows = self._conn.execute(
            "SELECT chunk_id FROM chunks WHERE project_id = ?", (project_id,)
        ).fetchall()
        return {row["chunk_id"] for row in rows}

    @staticmethod
    def _require_evidence_on_content_slide(slide) -> None:
        """非封面页必须至少一条材料证据（N3，"不给不存在资料补常识"的落地）。

        title 封面页豁免：docs/18 明确"零fact的封面无需调用语义模型"，
        封面只承载课题标题不含事实主张，允许无引用。
        """
        if slide.layout != "title" and not slide.evidence_chunk_ids:
            raise ValidationFailed(
                "content slides must cite at least one evidence chunk",
                {"slide_id": slide.id, "layout": slide.layout},
            )

    @staticmethod
    def _require_unique_slide_ids(slides) -> None:
        """slide_id 在计划内必须唯一（R00-C）：重复 id 会让引用/编辑定位歧义。"""
        ids = [s.id for s in slides]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValidationFailed(
                "slide ids must be unique within a plan",
                {"duplicate_slide_ids": duplicates},
            )

    @staticmethod
    def _content_covered_goals(slides) -> set:
        """内容页（非 title）声明覆盖的目标集合。

        title 封面按 docs/18 零 fact 豁免，不得代表任何教学目标的覆盖（R00-C）。
        """
        return {gi for s in slides if s.layout != "title" for gi in s.goal_indices}

    def _require_valid_goals_covered(self, slides, coverage) -> None:
        valid_goals = {
            c.goal_index for c in coverage if c.status in ("supported", "partial")
        }
        uncovered = sorted(valid_goals - self._content_covered_goals(slides))
        if uncovered:
            raise ValidationFailed(
                "valid goals must each be covered by at least one content slide",
                {"uncovered_goal_indices": uncovered},
            )

    # ---------- T09 门禁权威接缝 ----------

    def get_confirmed_plan_for_generation(
        self, project_id: str, plan_id: str, corpus_revision: int
    ) -> LessonPlan:
        """生成入口的权威读取接缝（R00-C 收口 N1）：精确按三要素定位，绝不猜。

        T09 必须经此接缝——直接读 plans 表会拿到 DB 里仍标 confirmed 的陈旧行
        （stale 只在读取路径计算，从不写库）；也不得按 created_at 取"最新确认
        计划"，生成请求绑定的是教师明确确认过的那个 plan_id。
        """
        plan = self._plans.get(plan_id)
        if plan is None or plan.project_id != project_id:
            raise PlanNotFound({"plan_id": plan_id})
        project = self._projects.get(project_id)
        if project is None:
            raise ProjectNotFound({"project_id": project_id})
        if corpus_revision != plan.corpus_revision:
            raise CorpusChanged(
                {
                    "requested": corpus_revision,
                    "plan_corpus_revision": plan.corpus_revision,
                }
            )
        if plan.corpus_revision != project.corpus_revision:
            # 语料已前进：该计划按 stale 对待，不存在"当前有效的确认"。
            raise CorpusChanged(
                {
                    "plan_corpus_revision": plan.corpus_revision,
                    "current": project.corpus_revision,
                }
            )
        if plan.status != "confirmed":
            raise PlanNotConfirmed({"plan_id": plan_id, "status": plan.status})
        return plan
