"""T08 大纲生成与教师确认：PlanService 单元测试。

provider 用 Fake 注入（协议状态机可 mock；真实模型链路是独立验收项）。
数据准备直接插 projects/chunks 行，与 T06 coverage 测试同构。
"""

import hashlib
import json

import pytest

from courseware_core.errors import (
    CorpusChanged,
    InsufficientEvidence,
    PlanNotFound,
    ProjectBusy,
    ProjectNotFound,
    ValidationFailed,
)
from courseware_core.llm.adapter import TypedCompletion, Usage
from courseware_core.models import (
    ConfirmPlanRequest,
    Job,
    LessonPlan,
    PlanProposal,
    PlanRequest,
)
from courseware_core.services.plan_service import PlanService

T0 = "2026-09-19T00:00:00+00:00"

GOAL_SUPPORTED = "NVIC优先级分组通过AIRCR配置"
GOAL_GAP = "EXTI外部中断线映射表"


def _course_json(goals):
    return json.dumps(
        {
            "topic": "STM32 中断",
            "audience": "大二",
            "duration_minutes": 45,
            "goals": goals,
            "target_slides": 8,
        }
    )


def insert_project(conn, project_id="prj1", *, goals=None, corpus_revision=1):
    goals = goals or [GOAL_SUPPORTED]
    with conn:
        conn.execute(
            "INSERT INTO projects (id, course_json, current_version,"
            " corpus_revision, active_job_id, consent_to_cloud_processing,"
            " created_at, updated_at) VALUES (?, ?, 0, ?, NULL, 1, ?, ?)",
            (project_id, _course_json(goals), corpus_revision, T0, T0),
        )


def insert_chunk(conn, chunk_id, *, project_id="prj1", document_id="mat1", rev=1, page=1, text):
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    with conn:
        conn.execute(
            "INSERT INTO materials (id, project_id, original_name, sha256, status,"
            " pdf_pages, usable_pages, corpus_revision, warnings_json, error_code,"
            " file_path, file_size, job_id, created_at, updated_at)"
            " VALUES (?, ?, 'x.pdf', ?, 'ready', 1, 1, ?, '[]', NULL,"
            " 'x.pdf', 100, NULL, ?, ?)"
            " ON CONFLICT(id) DO NOTHING",
            (document_id, project_id, "a" * 64, rev, T0, T0),
        )
        conn.execute(
            "INSERT INTO chunks (chunk_id, project_id, document_id, corpus_revision,"
            " pdf_page, page_start, page_end, text, text_sha256, extractor_version,"
            " tokenizer_version) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, 'pypdf-5.9.0-nfc-v1',"
            " 'jieba-0.42.1+ascii-v1')",
            (chunk_id, project_id, document_id, rev, page, len(text), text, sha),
        )


def proposal_json(chunk_id="chk1"):
    return {
        "slides": [
            {
                "id": "ps1",
                "title": "NVIC优先级分组",
                "purpose": "讲解AIRCR配置",
                "layout": "concept",
                "goal_indices": [0],
                "evidence_chunk_ids": [chunk_id],
            }
        ],
        "coverage_notes": [
            {"goal_index": 0, "candidate_chunk_ids": [chunk_id], "note": "模型自评"}
        ],
    }


class FakeProvider:
    def __init__(self, value=None, error=None, requests=1):
        self.value = value
        self.error = error
        self.requests = requests  # 模拟实际HTTP请求数（重试/修复都计入）
        self.calls = []

    def complete_json(self, stage, schema_name, messages, context):
        self.calls.append({"stage": stage, "schema_name": schema_name, "messages": messages})
        for _ in range(self.requests):
            context.budget.consume(1)
        if self.error is not None:
            raise self.error
        return TypedCompletion(
            value=self.value,
            usage=Usage(10, 5, 15),
            provider_request_id="fake-req",
            attempts=self.requests,
        )


def make_job(conn, job_id, project_id, *, corpus_revision=1, kind="plan"):
    with conn:
        conn.execute(
            "UPDATE projects SET active_job_id = ? WHERE id = ?", (job_id, project_id)
        )
        conn.execute(
            "INSERT INTO jobs (id, project_id, kind, status, stage, cancel_requested,"
            " base_version, corpus_revision, result_ref, error, llm_calls, request_id,"
            " created_at, updated_at)"
            " VALUES (?, ?, ?, 'running', 'planning', 0, 0, ?, NULL, NULL, 0, NULL, ?, ?)",
            (job_id, project_id, kind, corpus_revision, T0, T0),
        )
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def as_job(row) -> Job:
    return Job(**{k: row[k] for k in row.keys() if k in Job.model_fields})


def seed_supported_corpus(conn):
    insert_project(conn, goals=[GOAL_SUPPORTED])
    # 两个命中片段：T06 单候选保护会把唯一命中判 partial，supported 需≥2候选。
    insert_chunk(conn, "chk1", text="讲解：NVIC优先级分组通过AIRCR配置，需要先解锁KEYR。")
    insert_chunk(conn, "chk2", text="补充：NVIC优先级分组通过AIRCR配置组设置抢占与响应优先级。")


class TestCreatePlanJob:
    def test_acquires_lock_and_creates_plan_job(self, conn):
        seed_supported_corpus(conn)
        service = PlanService(conn)
        accepted = service.create_plan_job("prj1", PlanRequest(corpus_revision=1))
        assert accepted.job_id.startswith("job_")
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (accepted.job_id,)).fetchone()
        assert row["kind"] == "plan"
        assert row["status"] == "queued"
        assert row["corpus_revision"] == 1
        proj = conn.execute("SELECT active_job_id FROM projects WHERE id='prj1'").fetchone()
        assert proj["active_job_id"] == accepted.job_id

    def test_project_busy_when_lock_held(self, conn):
        seed_supported_corpus(conn)
        with conn:
            conn.execute("UPDATE projects SET active_job_id='job_other' WHERE id='prj1'")
        service = PlanService(conn)
        with pytest.raises(ProjectBusy):
            service.create_plan_job("prj1", PlanRequest(corpus_revision=1))

    def test_corpus_mismatch_rejected(self, conn):
        insert_project(conn, corpus_revision=2)
        service = PlanService(conn)
        with pytest.raises(CorpusChanged):
            service.create_plan_job("prj1", PlanRequest(corpus_revision=1))

    def test_project_not_found(self, conn):
        service = PlanService(conn)
        with pytest.raises(ProjectNotFound):
            service.create_plan_job("nope", PlanRequest(corpus_revision=1))


class TestHandlePlan:
    def test_all_supported_creates_draft(self, conn):
        seed_supported_corpus(conn)
        job = as_job(make_job(conn, "job_p", "prj1"))
        provider = FakeProvider(value=PlanProposal.model_validate(proposal_json()))
        service = PlanService(conn, provider=provider)
        ref = service.handle_plan(job)
        assert ref.type == "plan"
        plan = service.get_plan("prj1", ref.id)
        assert plan.status == "draft"
        assert plan.corpus_revision == 1
        assert plan.coverage[0].status == "supported"
        assert plan.accepted_goal_indices == [0]
        assert plan.project_id == "prj1"

    def test_gap_goal_creates_needs_material_with_visible_gap(self, conn):
        insert_project(conn, goals=[GOAL_SUPPORTED, GOAL_GAP])
        insert_chunk(conn, "chk1", text="讲解：NVIC优先级分组通过AIRCR配置。")
        # 缺口目标无任何材料支持。
        job = as_job(make_job(conn, "job_p", "prj1"))
        proposal = PlanProposal.model_validate(proposal_json())
        provider = FakeProvider(value=proposal)
        service = PlanService(conn, provider=provider)
        ref = service.handle_plan(job)
        plan = service.get_plan("prj1", ref.id)
        assert plan.status == "needs_material"
        statuses = {c.goal_index: c.status for c in plan.coverage}
        assert statuses[1] == "unsupported"
        # 缺口目标默认不进接受范围（不给不存在资料补常识，也不假绿）。
        assert plan.accepted_goal_indices == [0]

    def test_all_unsupported_blocks_job(self, conn):
        insert_project(conn, goals=[GOAL_GAP])
        insert_chunk(conn, "chk1", text="GPIO端口有八种工作模式，推挽开漏等。")
        job = as_job(make_job(conn, "job_p", "prj1"))
        provider = FakeProvider(value=PlanProposal.model_validate(proposal_json()))
        service = PlanService(conn, provider=provider)
        with pytest.raises(InsufficientEvidence):
            service.handle_plan(job)
        assert provider.calls == []  # 全缺口时不得先花模型调用再拒绝

    def test_prompt_contains_goals_and_evidence_not_model_notes(self, conn):
        seed_supported_corpus(conn)
        job = as_job(make_job(conn, "job_p", "prj1"))
        provider = FakeProvider(value=PlanProposal.model_validate(proposal_json()))
        service = PlanService(conn, provider=provider)
        service.handle_plan(job)
        call = provider.calls[0]
        assert call["stage"] == "plan_course"
        assert call["schema_name"] == "PlanProposal"
        flat = json.dumps(call["messages"], ensure_ascii=False)
        assert GOAL_SUPPORTED in flat
        assert "AIRCR" in flat  # 证据片段进入上下文

    def test_plan_coverage_is_server_side_not_model_self_report(self, conn):
        seed_supported_corpus(conn)
        job = as_job(make_job(conn, "job_p", "prj1"))
        bogus = proposal_json()
        bogus["coverage_notes"] = [
            {"goal_index": 0, "candidate_chunk_ids": ["chkX"], "note": "模型自称全部支持"}
        ]
        provider = FakeProvider(value=PlanProposal.model_validate(bogus))
        service = PlanService(conn, provider=provider)
        ref = service.handle_plan(job)
        plan = service.get_plan("prj1", ref.id)
        # coverage 真源=服务端 evaluate_goal_coverage；模型自评被忽略。
        assert set(plan.coverage[0].chunk_ids) == {"chk1", "chk2"}

    def test_slide_referencing_unknown_chunk_rejected(self, conn):
        seed_supported_corpus(conn)
        job = as_job(make_job(conn, "job_p", "prj1"))
        provider = FakeProvider(
            value=PlanProposal.model_validate(proposal_json(chunk_id="chk_fake"))
        )
        service = PlanService(conn, provider=provider)
        with pytest.raises(ValidationFailed):
            service.handle_plan(job)

    def test_context_trimming_per_page_8_chunks_and_8000_chars(self, conn):
        insert_project(conn, goals=[GOAL_SUPPORTED])
        # 造 12 个命中片段（TOP_K=12），每片段 900 字符 → 总量超 8000，必须裁剪。
        for i in range(12):
            text = "NVIC优先级分组通过AIRCR配置。" + ("填充" * 440)
            insert_chunk(conn, f"chk{i}", text=text)
        job = as_job(make_job(conn, "job_p", "prj1"))
        provider = FakeProvider(value=PlanProposal.model_validate(proposal_json()))
        service = PlanService(conn, provider=provider)
        service.handle_plan(job)
        flat = json.dumps(provider.calls[0]["messages"], ensure_ascii=False)
        assert len(flat) <= 9000  # 8000 正文预算 + 指令开销的宽松上限
        included = sum(1 for i in range(12) if f"【片段 chk{i}｜" in flat)
        assert included <= 8  # 每页最多8片段（docs/05 §9）

    def test_job_corpus_changed_defensively(self, conn):
        seed_supported_corpus(conn)
        job = as_job(make_job(conn, "job_p", "prj1", corpus_revision=1))
        with conn:
            conn.execute("UPDATE projects SET corpus_revision = 2 WHERE id='prj1'")
        provider = FakeProvider(value=PlanProposal.model_validate(proposal_json()))
        service = PlanService(conn, provider=provider)
        with pytest.raises(CorpusChanged):
            service.handle_plan(job)


class TestConfirmPlan:
    def _draft_plan(self, conn, *, goals=None, provider_value=None):
        goals = goals or [GOAL_SUPPORTED]
        if goals == [GOAL_SUPPORTED]:
            seed_supported_corpus(conn)
        else:
            insert_project(conn, goals=goals)
            insert_chunk(conn, "chk1", text="讲解：NVIC优先级分组通过AIRCR配置。")
        job = as_job(make_job(conn, "job_p", "prj1"))
        provider = FakeProvider(
            value=provider_value or PlanProposal.model_validate(proposal_json())
        )
        service = PlanService(conn, provider=provider)
        ref = service.handle_plan(job)
        return service, ref.id

    def test_confirm_happy_path(self, conn):
        service, plan_id = self._draft_plan(conn)
        request = ConfirmPlanRequest(
            corpus_revision=1,
            slides=[
                {
                    "id": "ps1",
                    "title": "改过的标题",
                    "purpose": "教师调整后用途",
                    "layout": "two_column",
                    "goal_indices": [0],
                    "evidence_chunk_ids": ["chk1"],
                }
            ],
            accepted_goal_indices=[0],
            acknowledged=True,
        )
        plan = service.confirm_plan("prj1", plan_id, request)
        assert plan.status == "confirmed"
        assert plan.slides[0].title == "改过的标题"
        assert plan.slides[0].layout == "two_column"

    def test_confirm_rejects_gap_goal_in_accepted(self, conn):
        service, plan_id = self._draft_plan(conn, goals=[GOAL_SUPPORTED, GOAL_GAP])
        request = ConfirmPlanRequest(
            corpus_revision=1,
            slides=[
                {
                    "id": "ps1",
                    "title": "t",
                    "purpose": "p",
                    "layout": "concept",
                    "goal_indices": [0, 1],
                    "evidence_chunk_ids": ["chk1"],
                }
            ],
            accepted_goal_indices=[0, 1],
            acknowledged=True,
        )
        with pytest.raises(ValidationFailed) as exc:
            service.confirm_plan("prj1", plan_id, request)
        assert 1 in exc.value.details["gap_goals"]

    def test_confirm_rejects_slide_touching_unaccepted_goal(self, conn):
        service, plan_id = self._draft_plan(conn)
        request = ConfirmPlanRequest(
            corpus_revision=1,
            slides=[
                {
                    "id": "ps1",
                    "title": "t",
                    "purpose": "p",
                    "layout": "concept",
                    "goal_indices": [0],
                    "evidence_chunk_ids": ["chk1"],
                },
                {
                    "id": "ps2",
                    "title": "t2",
                    "purpose": "p2",
                    "layout": "concept",
                    "goal_indices": [3],
                    "evidence_chunk_ids": ["chk1"],
                },
            ],
            accepted_goal_indices=[0],
            acknowledged=True,
        )
        with pytest.raises(ValidationFailed):
            service.confirm_plan("prj1", plan_id, request)

    def test_confirm_rejects_unknown_chunk_reference(self, conn):
        service, plan_id = self._draft_plan(conn)
        request = ConfirmPlanRequest(
            corpus_revision=1,
            slides=[
                {
                    "id": "ps1",
                    "title": "t",
                    "purpose": "p",
                    "layout": "concept",
                    "goal_indices": [0],
                    "evidence_chunk_ids": ["chk_fake"],
                }
            ],
            accepted_goal_indices=[0],
            acknowledged=True,
        )
        with pytest.raises(ValidationFailed):
            service.confirm_plan("prj1", plan_id, request)

    def test_confirm_stale_plan_rejected(self, conn):
        service, plan_id = self._draft_plan(conn)
        with conn:
            conn.execute("UPDATE projects SET corpus_revision = 2 WHERE id='prj1'")
        request = ConfirmPlanRequest(
            corpus_revision=1,
            slides=[
                {
                    "id": "ps1",
                    "title": "t",
                    "purpose": "p",
                    "layout": "concept",
                    "goal_indices": [0],
                    "evidence_chunk_ids": ["chk1"],
                }
            ],
            accepted_goal_indices=[0],
            acknowledged=True,
        )
        with pytest.raises(CorpusChanged):
            service.confirm_plan("prj1", plan_id, request)

    def test_confirm_request_revision_mismatch_rejected(self, conn):
        service, plan_id = self._draft_plan(conn)
        request = ConfirmPlanRequest(
            corpus_revision=2,
            slides=[
                {
                    "id": "ps1",
                    "title": "t",
                    "purpose": "p",
                    "layout": "concept",
                    "goal_indices": [0],
                    "evidence_chunk_ids": ["chk1"],
                }
            ],
            accepted_goal_indices=[0],
            acknowledged=True,
        )
        with pytest.raises(CorpusChanged):
            service.confirm_plan("prj1", plan_id, request)

    def test_confirm_idempotent_replay(self, conn):
        service, plan_id = self._draft_plan(conn)
        request = ConfirmPlanRequest(
            corpus_revision=1,
            slides=[
                {
                    "id": "ps1",
                    "title": "t",
                    "purpose": "p",
                    "layout": "concept",
                    "goal_indices": [0],
                    "evidence_chunk_ids": ["chk1"],
                }
            ],
            accepted_goal_indices=[0],
            acknowledged=True,
        )
        first = service.confirm_plan("prj1", plan_id, request)
        second = service.confirm_plan("prj1", plan_id, request)
        assert first == second

    def test_confirm_not_found_and_cross_project(self, conn):
        seed_supported_corpus(conn)
        insert_project(conn, "prj2")
        service = PlanService(conn)
        request = ConfirmPlanRequest(
            corpus_revision=1,
            slides=[
                {
                    "id": "ps1",
                    "title": "t",
                    "purpose": "p",
                    "layout": "concept",
                    "goal_indices": [0],
                    "evidence_chunk_ids": [],
                }
            ],
            accepted_goal_indices=[0],
            acknowledged=True,
        )
        with pytest.raises(PlanNotFound):
            service.confirm_plan("prj1", "plan_missing", request)


class TestStaleOnRead:
    def test_get_plan_reports_stale_after_new_material(self, conn):
        insert_project(conn, goals=[GOAL_SUPPORTED], corpus_revision=1)
        insert_chunk(conn, "chk1", text="NVIC优先级分组通过AIRCR寄存器实现。", rev=1)
        job = as_job(make_job(conn, "job_p", "prj1"))
        provider = FakeProvider(value=PlanProposal.model_validate(proposal_json()))
        service = PlanService(conn, provider=provider)
        ref = service.handle_plan(job)
        # 模拟新材料成功入库：项目 corpus 前进，plan 不动。
        insert_chunk(conn, "chk9", text="新章节内容。", rev=2)
        with conn:
            conn.execute("UPDATE projects SET corpus_revision = 2 WHERE id='prj1'")
        plan = service.get_plan("prj1", ref.id)
        assert plan.status == "stale"


class TestReviewClosedLoop:
    """T08 Review 闭环新增：N1/N2/N3/N4/N5 行为固化。"""

    def test_slide_referencing_hit_but_trimmed_chunk_rejected(self, conn):
        # N2：chunk 命中检索但被8000字符预算裁掉——模型没见过却引用=无依据。
        insert_project(conn, goals=[GOAL_SUPPORTED])
        for i in range(12):
            text = "NVIC优先级分组通过AIRCR配置。" + ("填充" * 440)
            insert_chunk(conn, f"chunk{i}", text=text)
        job = as_job(make_job(conn, "job_p", "prj1"))
        provider = FakeProvider(value=PlanProposal.model_validate(
            proposal_json(chunk_id="chunk11")))
        service = PlanService(conn, provider=provider)
        with pytest.raises(ValidationFailed) as exc:
            service.handle_plan(job)
        assert "chunk11" in exc.value.details["unknown_chunk_ids"]

    def test_content_slide_without_evidence_rejected(self, conn):
        # N3：非封面页空引用=常识填页，生成路径拒绝。
        seed_supported_corpus(conn)
        job = as_job(make_job(conn, "job_p", "prj1"))
        bogus = proposal_json()
        bogus["slides"][0]["evidence_chunk_ids"] = []
        provider = FakeProvider(value=PlanProposal.model_validate(bogus))
        service = PlanService(conn, provider=provider)
        with pytest.raises(ValidationFailed):
            service.handle_plan(job)

    def test_title_slide_without_evidence_allowed(self, conn):
        # N3豁免：零fact封面允许无引用（docs/18）。
        seed_supported_corpus(conn)
        job = as_job(make_job(conn, "job_p", "prj1"))
        cover = proposal_json()
        cover["slides"][0]["layout"] = "title"
        cover["slides"][0]["evidence_chunk_ids"] = []
        provider = FakeProvider(value=PlanProposal.model_validate(cover))
        service = PlanService(conn, provider=provider)
        ref = service.handle_plan(job)
        plan = service.get_plan("prj1", ref.id)
        assert plan.slides[0].evidence_chunk_ids == []

    def test_llm_calls_accumulated_on_failure(self, conn):
        # N4：调用失败也要记账（已发生的请求可能计费，费用观测不得虚报0）。
        from courseware_core.errors import ModelRateLimited
        seed_supported_corpus(conn)
        job = as_job(make_job(conn, "job_p", "prj1"))
        provider = FakeProvider(error=ModelRateLimited(), requests=2)
        service = PlanService(conn, provider=provider)
        with pytest.raises(ModelRateLimited):
            service.handle_plan(job)
        row = conn.execute("SELECT llm_calls FROM jobs WHERE id='job_p'").fetchone()
        assert row["llm_calls"] == 2

    def test_confirm_divergent_payload_after_confirmed_rejected(self, conn):
        # N5：已确认+不同载荷=矛盾请求，须拒绝而非静默返回旧计划。
        service, plan_id = TestConfirmPlan._draft_plan(TestConfirmPlan(), conn)
        base = {
            "corpus_revision": 1,
            "slides": [
                {
                    "id": "ps1", "title": "t", "purpose": "p",
                    "layout": "concept", "goal_indices": [0],
                    "evidence_chunk_ids": ["chk1"],
                }
            ],
            "accepted_goal_indices": [0],
            "acknowledged": True,
        }
        service.confirm_plan("prj1", plan_id, ConfirmPlanRequest(**base))
        diverged = dict(base)
        diverged["slides"] = [dict(base["slides"][0], title="改过的标题")]
        with pytest.raises(ValidationFailed):
            service.confirm_plan("prj1", plan_id, ConfirmPlanRequest(**diverged))

    def test_get_current_confirmed_plan_seam(self, conn):
        # N1：T09 门禁权威接缝——确认后可取；语料前进后无有效计划。
        service, plan_id = TestConfirmPlan._draft_plan(TestConfirmPlan(), conn)
        request = ConfirmPlanRequest(
            corpus_revision=1,
            slides=[
                {
                    "id": "ps1", "title": "t", "purpose": "p",
                    "layout": "concept", "goal_indices": [0],
                    "evidence_chunk_ids": ["chk1"],
                }
            ],
            accepted_goal_indices=[0],
            acknowledged=True,
        )
        assert service.get_current_confirmed_plan("prj1") is None
        service.confirm_plan("prj1", plan_id, request)
        current = service.get_current_confirmed_plan("prj1")
        assert current is not None and current.status == "confirmed"
        with conn:
            conn.execute("UPDATE projects SET corpus_revision = 2 WHERE id='prj1'")
        assert service.get_current_confirmed_plan("prj1") is None
