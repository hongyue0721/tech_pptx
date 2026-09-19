"""T08 大纲生成与教师确认：Planner.create/confirm（docs/18）。

- create：worker plan handler 内执行——逐目标coverage（服务端计算，真源）+
  按 docs/05 裁剪证据上下文 → adapter 产出 PlanProposal → 服务端组装
  LessonPlan（draft/needs_material），停在教师确认，绝不自行 confirmed。
- confirm：教师调整 slides/接受范围后服务端重检引用与 coverage；
  缺口目标必须被明确移出接受范围（不假绿）；语料前进即 stale 拒确认。
- 全目标无支持 → InsufficientEvidence（job blocked，不烧模型调用）。
"""

import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from courseware_core.errors import (
    CorpusChanged,
    InsufficientEvidence,
    ModelProtocolError,
    PlanNotFound,
    ProjectNotFound,
    ValidationFailed,
)
from courseware_core.llm.budget import CallBudget, JobContext
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
from courseware_core.services.coverage_service import (
    TOP_K,
    evaluate_goal_coverage,
)
from courseware_core.storage.job_repository import JobRepository
from courseware_core.storage.plan_repository import PlanRepository, new_plan_id
from courseware_core.storage.project_repository import ProjectRepository

# 上下文预算（docs/05 §9）：去重后每目标最多8片段、总正文约8000字符。
# 换供应商/更大规模需重估时改这里并同步文档，不散落魔法数。
CONTEXT_PER_GOAL_MAX = 8
CONTEXT_CHAR_BUDGET = 8000

# plan 单次逻辑调用的HTTP上限：1原始+1修复+退避重试余量（docs/06 重试矩阵）。
PLAN_CALL_BUDGET = 4

PROMPT_VERSION = "plan-v1"

PLAN_SYSTEM_PROMPT = (
    f"[prompt_version={PROMPT_VERSION}] 你是课件大纲助手。"
    "只依据用户消息中给出的教材片段组织大纲，不得用片段之外的常识补充内容；"
    "每页 evidence_chunk_ids 必须非空且只能引用给定片段的编号；"
    "无法找到支持片段的目标不要为其安排页面。"
    "只输出一个符合 PlanProposal 结构的 JSON 对象："
    "slides（1-12页：id、title≤40字、purpose≤240字、layout为"
    " title/concept/two_column/process_example 之一、goal_indices、"
    "evidence_chunk_ids）与 coverage_notes（每目标一条）。不要输出其他文字。"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PlanService:
    def __init__(self, conn: sqlite3.Connection, provider=None):
        self._conn = conn
        self._provider = provider
        self._plans = PlanRepository(conn)
        self._projects = ProjectRepository(conn)
        self._jobs = JobRepository(conn)

    # ---------- 受理 ----------

    def create_plan_job(
        self, project_id: str, request: PlanRequest, request_id: Optional[str] = None
    ) -> JobAccepted:
        project = self._projects.get(project_id)
        if project is None:
            raise ProjectNotFound({"project_id": project_id})
        # 请求必须绑定当前语料快照；过期视图或超前视图都拒绝（api.md：绑定corpus_revision）。
        if request.corpus_revision != project.corpus_revision:
            raise CorpusChanged(
                {
                    "requested": request.corpus_revision,
                    "current": project.corpus_revision,
                }
            )
        job_id = f"job_{secrets.token_hex(16)}"
        self._plans.create_with_job(
            project_id, job_id=job_id, corpus_revision=request.corpus_revision,
            request_id=request_id,
        )
        return JobAccepted(job_id=job_id)

    # ---------- worker 执行 ----------

    def handle_plan(self, job: Job) -> JobResultRef:
        project = self._projects.get(job.project_id)
        if project is None:
            raise ProjectNotFound({"project_id": job.project_id})
        # 防御性复核：写锁保证执行期语料不变，若不变式被破坏宁可失败也不混语料。
        if job.corpus_revision != project.corpus_revision:
            raise CorpusChanged(
                {
                    "job_corpus_revision": job.corpus_revision,
                    "current": project.corpus_revision,
                }
            )
        goals = project.course.goals
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
        messages = self._build_messages(project, goals, selected)

        provider = self._provider
        if provider is None:
            raise ModelProtocolError("llm provider is not configured for plan stage")
        context = JobContext(
            budget=CallBudget(max_calls=PLAN_CALL_BUDGET),
            cancel_check=self._make_cancel_check(job.id),
        )
        try:
            completion = provider.complete_json(
                "plan_course", "PlanProposal", messages, context
            )
        finally:
            # 费用记账不依赖成功路径（N4）：失败/取消时按已消耗请求数如实累计，
            # budget.used 就是实际HTTP请求数（含重试与修复）。
            self._accumulate_llm_calls(job.id, context.budget.used)
        proposal: PlanProposal = completion.value

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

        has_gap = any(c.status in ("unsupported", "conflict") for c in coverage)
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

    def _make_cancel_check(self, job_id: str):
        """轮询取消位（T04-N4 收口：业务 handler 的取消通道）。"""

        def _cancelled() -> bool:
            current = self._jobs.get(job_id)
            return bool(current and current.cancel_requested)

        return _cancelled

    def _accumulate_llm_calls(self, job_id: str, attempts: int) -> None:
        # jobs.llm_calls 列 CHECK 0-24（docs/06 预算）；封顶不报错，如实累计。
        with self._conn:
            self._conn.execute(
                "UPDATE jobs SET llm_calls = MIN(24, llm_calls + ?) WHERE id = ?",
                (attempts, job_id),
            )

    def _build_messages(self, project, goals, selected) -> list:
        lines = [
            f"课题：{project.course.topic}",
            f"对象：{project.course.audience}；时长：{project.course.duration_minutes}分钟",
            "教学目标：",
        ]
        lines += [f"{i}. {goal}" for i, goal in enumerate(goals)]
        lines.append("教材片段：")
        for goal_index, hit in selected:
            lines.append(
                f"【片段 {hit.chunk_id}｜目标{goal_index}｜第{hit.pdf_page}页】{hit.text}"
            )
        return [
            {"role": "system", "content": PLAN_SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(lines)},
        ]

    @staticmethod
    def _assemble_context(hits_by_goal: dict):
        """按目标轮转取片段：每目标≤8、全局≤8000字符（docs/05），先到先得会饿死
        后面的目标，所以轮转（round-robin）保证多目标公平。"""
        selected = []
        used_ids: set[str] = set()
        budget = CONTEXT_CHAR_BUDGET
        for rank in range(CONTEXT_PER_GOAL_MAX):
            for goal_index in sorted(hits_by_goal):
                hits = hits_by_goal[goal_index]
                if rank >= len(hits):
                    continue
                hit = hits[rank]
                if hit.chunk_id in used_ids:
                    continue
                if budget - len(hit.text) < 0:
                    return selected
                used_ids.add(hit.chunk_id)
                budget -= len(hit.text)
                selected.append((goal_index, hit))
        return selected

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

        confirmed = plan.model_copy(
            update={
                "status": "confirmed",
                "slides": request.slides,
                "accepted_goal_indices": request.accepted_goal_indices,
            }
        )
        self._plans.update(confirmed)
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

    # ---------- T09 门禁权威接缝 ----------

    def get_current_confirmed_plan(self, project_id: str) -> Optional[LessonPlan]:
        """当前语料快照下唯一有效的已确认计划；语料前进即无有效计划（stale不算）。

        T09 生成入口必须经此接缝——直接读 plans 表会拿到 DB 里仍标 confirmed
        的陈旧行（stale 只在读取路径计算，从不写库）。
        """
        project = self._projects.get(project_id)
        if project is None:
            raise ProjectNotFound({"project_id": project_id})
        rows = self._conn.execute(
            "SELECT id FROM plans WHERE project_id = ? AND status = 'confirmed'"
            " ORDER BY created_at DESC",
            (project_id,),
        ).fetchall()
        for row in rows:
            plan = self._plans.get(row["id"])
            if plan is not None and plan.corpus_revision == project.corpus_revision:
                return plan
        return None
