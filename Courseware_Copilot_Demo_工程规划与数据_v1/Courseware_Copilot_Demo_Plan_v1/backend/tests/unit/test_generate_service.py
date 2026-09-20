"""T09 候选生成与语义核验：GenerateService 单测（ScriptedProvider，零真实模型）。

流程契约（docs/18:39/43、docs/06:25-28、docs/04:41）：
确认接缝 → 每批2-3页 ContentProposal → locator 转存储 Claim（一次修复机会）
→ Verifier 批量核验（零fact页不调模型）→ 结构/关系检查 → CandidateChange
（ready/blocked 由 can_commit 门决定）→ 教师 commit 才动版本（循环③）。
"""

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from courseware_core.errors import (
    ChangeNotCommittable,
    ConsentRequired,
    CorpusChanged,
    DomainError,
    JobCancelled,
    ModelTimeout,
    PlanNotConfirmed,
    PlanNotFound,
    VersionConflict,
)
from courseware_core.llm.adapter import TypedCompletion, Usage
from courseware_core.models import (
    CommitRequest,
    ContentProposal,
    GenerateRequest,
    Job,
    LessonPlan,
    SemanticVerdicts,
    VisibleTextAudit,
)
from courseware_core.services.generate_service import GenerateService
from courseware_core.services.plan_service import PlanService
from courseware_core.storage.change_repository import ChangeRepository
from courseware_core.storage.database import connect

T0 = "2026-09-19T00:00:00+00:00"
GOAL = "NVIC优先级分组通过AIRCR配置"
CHUNK1_TEXT = "讲解：NVIC优先级分组通过AIRCR配置，需要先解锁KEYR。"
CHUNK2_TEXT = "补充：NVIC优先级分组通过AIRCR配置组设置抢占与响应优先级。"
QUOTE1 = "NVIC优先级分组通过AIRCR配置"


class ScriptedProvider:
    """按 stage 脚本化响应队列；耗尽即测试失败（不静默多调）。"""

    def __init__(self, by_stage: dict[str, list]):
        self._by_stage = {k: list(v) for k, v in by_stage.items()}
        self.calls: list[dict] = []

    def complete_json(self, stage, schema_name, messages, context):
        self.calls.append(
            {"stage": stage, "schema_name": schema_name, "messages": messages,
             "context": context}
        )
        context.budget.consume(1)
        queue = self._by_stage.get(stage)
        if not queue:
            raise AssertionError(f"no scripted response for stage={stage}")
        value = queue.pop(0)
        if callable(value):
            # 回调注入副作用（如置取消位/压 deadline），模拟"最后一次模型
            # 调用完成之后、候选写库之前"才发生的状态变化。
            value = value(context)
        if isinstance(value, Exception):
            raise value
        return TypedCompletion(
            value=value, usage=Usage(10, 5, 15),
            provider_request_id=f"fake-{len(self.calls)}", attempts=1,
        )

    def stages(self) -> list[str]:
        return [c["stage"] for c in self.calls]


def _insert(conn, sql, *args):
    with conn:
        conn.execute(sql, args)


def seed_project(conn, *, consent=True, corpus_revision=1):
    course = json.dumps(
        {"topic": "STM32 中断", "audience": "大二", "duration_minutes": 45,
         "goals": [GOAL], "target_slides": 8}
    )
    _insert(
        conn,
        "INSERT INTO projects (id, course_json, current_version, corpus_revision,"
        " active_job_id, consent_to_cloud_processing, created_at, updated_at)"
        " VALUES ('prj1', ?, 0, ?, NULL, ?, ?, ?)",
        course, corpus_revision, int(consent), T0, T0,
    )


def seed_chunks(conn):
    sha1 = hashlib.sha256(CHUNK1_TEXT.encode()).hexdigest()
    sha2 = hashlib.sha256(CHUNK2_TEXT.encode()).hexdigest()
    _insert(
        conn,
        "INSERT INTO materials (id, project_id, original_name, sha256, status,"
        " pdf_pages, usable_pages, corpus_revision, warnings_json, error_code,"
        " file_path, file_size, job_id, created_at, updated_at)"
        " VALUES ('mat1','prj1','x.pdf',?,'ready',1,1,1,'[]',NULL,'x.pdf',100,NULL,?,?)",
        "a" * 64, T0, T0,
    )
    for cid, text, sha in (("chk1", CHUNK1_TEXT, sha1), ("chk2", CHUNK2_TEXT, sha2)):
        _insert(
            conn,
            "INSERT INTO chunks (chunk_id, project_id, document_id, corpus_revision,"
            " pdf_page, page_start, page_end, text, text_sha256, extractor_version,"
            " tokenizer_version) VALUES (?, 'prj1','mat1',1,1,0,?,?,?,"
            " 'pypdf-5.9.0-nfc-v1','jieba-0.42.1+ascii-v1')",
            cid, len(text), text, sha,
        )


def plan_slides(n=1, layout="concept"):
    return [
        {"id": f"ps{i+1}", "title": f"NVIC分组{i+1}", "purpose": "讲解AIRCR配置",
         "layout": layout, "goal_indices": [0], "evidence_chunk_ids": ["chk1"]}
        for i in range(n)
    ]


def seed_confirmed_plan(conn, *, slides=None, status="confirmed"):
    seed_project(conn)
    seed_chunks(conn)
    plan = LessonPlan.model_validate(
        {
            "id": "plan1", "project_id": "prj1", "corpus_revision": 1, "status": status,
            "coverage": [{"goal_index": 0, "status": "supported",
                          "chunk_ids": ["chk1", "chk2"], "note": ""}],
            "slides": slides or plan_slides(1),
            "accepted_goal_indices": [0],
            "created_at": T0,
        }
    )
    _insert(
        conn,
        "INSERT INTO plans (id, project_id, corpus_revision, status, plan_json,"
        " created_at, updated_at) VALUES ('plan1','prj1',1,?,?,?,?)",
        status, plan.model_dump_json(), T0, T0,
    )
    return plan


def make_generate_job(conn, job_id, *, plan_id="plan1", base_version=0,
                      corpus_revision=1, deadline_at=None, cancel=False):
    params = json.dumps({"plan_id": plan_id, "base_version": base_version})
    _insert(
        conn,
        "UPDATE projects SET active_job_id = ? WHERE id = 'prj1'", job_id,
    )
    _insert(
        conn,
        "INSERT INTO jobs (id, project_id, kind, status, stage, cancel_requested,"
        " base_version, corpus_revision, result_ref, error, llm_calls, request_id,"
        " deadline_at, params_json, created_at, updated_at)"
        " VALUES (?, 'prj1', 'generate', 'running', 'queued', ?, 0, ?, NULL, NULL,"
        " 0, NULL, ?, ?, ?, ?)",
        job_id, int(cancel), corpus_revision, deadline_at, params, T0, T0,
    )
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return Job(**{k: row[k] for k in row.keys() if k in Job.model_fields})


def content_proposal(slide_id="ps1", claim_id="clm1", *, quote=QUOTE1,
                     chunk_id="chk1", text="NVIC优先级分组通过AIRCR配置。"):
    return ContentProposal.model_validate(
        {
            "claims": [{"id": claim_id, "text": text, "kind": "direct",
                        "evidence_refs": [{"chunk_id": chunk_id, "quote": quote}],
                        "rationale": None}],
            "slides": [{"id": slide_id, "title": "NVIC分组", "layout": "concept",
                        "blocks": [{"type": "fact", "claim_id": claim_id}]}],
            "missing_evidence": [],
        }
    )


def zero_fact_proposal(slide_id="ps1"):
    return ContentProposal.model_validate(
        {
            "claims": [],
            "slides": [{"id": slide_id, "title": "封面", "layout": "title",
                        "blocks": [{"type": "teaching", "text": "本节主题引入。"}]}],
            "missing_evidence": [],
        }
    )


def multi_proposal(items):
    """一批多页：items=[(slide_id, claim_id)]，每页一个 fact claim。"""
    return ContentProposal.model_validate(
        {
            "claims": [
                {"id": cid, "text": "NVIC优先级分组通过AIRCR配置。", "kind": "direct",
                 "evidence_refs": [{"chunk_id": "chk1", "quote": QUOTE1}],
                 "rationale": None}
                for _, cid in items
            ],
            "slides": [
                {"id": sid, "title": "NVIC分组", "layout": "concept",
                 "blocks": [{"type": "fact", "claim_id": cid}]}
                for sid, cid in items
            ],
            "missing_evidence": [],
        }
    )


def verdicts(*claim_ids, status="supported", unbound=None):
    return SemanticVerdicts.model_validate(
        {
            "checks": [{"claim_id": c, "status": status, "reason": "原文直接支持。"}
                       for c in claim_ids],
            "unbound_assertions": unbound or [],
        }
    )


UNBOUND = [{
    "slide_id": "ps1", "field_path": "blocks[1].text",
    "text": "抢占优先级数值越小越优先。", "reason": "未绑定证据的专业断言。",
}]


class TestCreateGenerateJob:
    def test_accept_creates_generate_job_holding_lock(self, conn):
        seed_confirmed_plan(conn)
        service = GenerateService(conn)
        accepted = service.create_generate_job(
            "prj1", GenerateRequest(plan_id="plan1", base_version=0, corpus_revision=1)
        )
        assert accepted.job_id.startswith("job_")
        row = conn.execute(
            "SELECT kind, status, deadline_at, params_json FROM jobs WHERE id = ?",
            (accepted.job_id,),
        ).fetchone()
        assert row["kind"] == "generate" and row["status"] == "queued"
        assert row["deadline_at"] is not None
        assert json.loads(row["params_json"]) == {"plan_id": "plan1", "base_version": 0}
        proj = conn.execute(
            "SELECT active_job_id FROM projects WHERE id='prj1'"
        ).fetchone()
        assert proj["active_job_id"] == accepted.job_id

    def test_denied_without_consent(self, conn):
        seed_confirmed_plan(conn)
        _insert(conn, "UPDATE projects SET consent_to_cloud_processing=0 WHERE id='prj1'",)
        service = GenerateService(conn)
        with pytest.raises(ConsentRequired):
            service.create_generate_job(
                "prj1", GenerateRequest(plan_id="plan1", base_version=0, corpus_revision=1)
            )

    def test_unconfirmed_plan_rejected(self, conn):
        seed_confirmed_plan(conn, status="draft")
        service = GenerateService(conn)
        with pytest.raises(PlanNotConfirmed):
            service.create_generate_job(
                "prj1", GenerateRequest(plan_id="plan1", base_version=0, corpus_revision=1)
            )

    def test_corpus_advanced_rejected(self, conn):
        seed_confirmed_plan(conn)
        service = GenerateService(conn)
        with pytest.raises(CorpusChanged):
            service.create_generate_job(
                "prj1", GenerateRequest(plan_id="plan1", base_version=0, corpus_revision=2)
            )

    def test_stale_base_version_rejected(self, conn):
        seed_confirmed_plan(conn)
        service = GenerateService(conn)
        with pytest.raises(VersionConflict):
            service.create_generate_job(
                "prj1", GenerateRequest(plan_id="plan1", base_version=5, corpus_revision=1)
            )

    def test_unknown_plan_rejected(self, conn):
        seed_confirmed_plan(conn)
        service = GenerateService(conn)
        with pytest.raises(PlanNotFound):
            service.create_generate_job(
                "prj1", GenerateRequest(plan_id="plan_x", base_version=0, corpus_revision=1)
            )


class TestHandleGenerate:
    def test_happy_path_produces_ready_candidate(self, conn):
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_g1")
        provider = ScriptedProvider(
            {"generate_content": [content_proposal()], "verify_claims": [verdicts("clm1")],
             "audit_visible_text": [audit_pass("ps1")]}
        )
        service = GenerateService(conn, provider=provider)
        ref = service.handle_generate(job)
        assert ref.type == "change"
        change = ChangeRepository(conn).get(ref.id)
        assert change is not None and change.status == "ready"
        assert change.validation.can_commit is True
        # 证据坐标由服务端从存储解析填充（docs/04 §19），非模型自填。
        span = change.candidate.claims[0].evidence_refs[0]
        assert (span.document_id, span.pdf_page) == ("mat1", 1)
        assert CHUNK1_TEXT[span.start:span.end] == span.quote
        assert span.chunk_id == "chk1"

    def test_stage_progression_and_verify_after_content(self, conn):
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_g2")
        seen = {}

        provider = ScriptedProvider(
            {"generate_content": [content_proposal()], "verify_claims": [verdicts("clm1")],
             "audit_visible_text": [audit_pass("ps1")]}
        )
        orig = provider.complete_json

        def probe(stage, schema_name, messages, context):
            seen[stage] = conn.execute(
                "SELECT stage FROM jobs WHERE id='job_g2'"
            ).fetchone()["stage"]
            return orig(stage, schema_name, messages, context)

        provider.complete_json = probe
        service = GenerateService(conn, provider=provider)
        service.handle_generate(job)
        assert seen["generate_content"] == "generating"
        assert seen["verify_claims"] == "validating"

    def test_fake_quote_repaired_once_then_ready(self, conn):
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_g3")
        bad = content_proposal(quote="这段教材里根本没有的话")
        good = content_proposal()
        provider = ScriptedProvider(
            {"generate_content": [bad, good], "verify_claims": [verdicts("clm1")],
             "audit_visible_text": [audit_pass("ps1")]}
        )
        service = GenerateService(conn, provider=provider)
        ref = service.handle_generate(job)
        change = ChangeRepository(conn).get(ref.id)
        assert change.status == "ready"
        assert provider.stages().count("generate_content") == 2

    def test_fake_quote_survives_repair_blocks_candidate(self, conn):
        # 一次修复仍假引用：locator invalid → 该 claim 不进语义核验（not_checked）
        # → can_commit=false、候选 blocked——模型 verdict 不得掩盖定位失败（docs/18:43）。
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_g4")
        bad = content_proposal(quote="这段教材里根本没有的话")
        provider = ScriptedProvider(
            {"generate_content": [bad, bad], "verify_claims": [verdicts("clm1")],
             "audit_visible_text": [audit_pass("ps1")]}
        )
        service = GenerateService(conn, provider=provider)
        ref = service.handle_generate(job)
        change = ChangeRepository(conn).get(ref.id)
        assert change.status == "blocked"
        assert change.validation.can_commit is False
        check = change.validation.claim_checks[0]
        assert check.locator_status == "invalid"
        assert check.semantic_status == "not_checked"
        # 定位失败的 claim 不进模型核验队列。
        assert provider.stages().count("verify_claims") == 0

    def test_unsupported_verdict_blocks(self, conn):
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_g5")
        provider = ScriptedProvider(
            {"generate_content": [content_proposal()],
             "verify_claims": [verdicts("clm1", status="unsupported")],
             "audit_visible_text": [audit_pass("ps1")]}
        )
        service = GenerateService(conn, provider=provider)
        ref = service.handle_generate(job)
        change = ChangeRepository(conn).get(ref.id)
        assert change.status == "blocked"
        assert change.validation.can_commit is False

    def test_partial_verdict_blocks(self, conn):
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_g6")
        provider = ScriptedProvider(
            {"generate_content": [content_proposal()],
             "verify_claims": [verdicts("clm1", status="partial")],
             "audit_visible_text": [audit_pass("ps1")]}
        )
        service = GenerateService(conn, provider=provider)
        ref = service.handle_generate(job)
        assert ChangeRepository(conn).get(ref.id).status == "blocked"

    def test_missing_verdict_not_greenwashed(self, conn):
        # 模型对某 claim 漏答（返回了别的 id）：不得跳过变绿（verify.md），
        # 缺失方记 not_checked → blocked。
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_g7")
        provider = ScriptedProvider(
            {"generate_content": [content_proposal()],
             "verify_claims": [verdicts("ghost_claim")],
             "audit_visible_text": [audit_pass("ps1")]}
        )
        service = GenerateService(conn, provider=provider)
        ref = service.handle_generate(job)
        change = ChangeRepository(conn).get(ref.id)
        assert change.status == "blocked"
        assert change.validation.claim_checks[0].semantic_status == "not_checked"

    def test_unbound_assertions_block(self, conn):
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_g8")
        provider = ScriptedProvider(
            {"generate_content": [content_proposal()],
             "verify_claims": [verdicts("clm1", unbound=UNBOUND)],
             "audit_visible_text": [audit_pass("ps1")]}
        )
        service = GenerateService(conn, provider=provider)
        ref = service.handle_generate(job)
        change = ChangeRepository(conn).get(ref.id)
        assert change.status == "blocked"
        assert len(change.validation.unbound_assertions) == 1

    def test_zero_fact_cover_skips_semantic_model(self, conn):
        # 教师确认计划里的 title 封面：零fact不调语义模型（docs/18:43）且豁免
        # 可见文字审计（循环①：豁免判据=计划 layout，非模型自报）。
        seed_confirmed_plan(conn, slides=plan_slides(1, layout="title"))
        job = make_generate_job(conn, "job_g9")
        provider = ScriptedProvider({"generate_content": [zero_fact_proposal()]})
        service = GenerateService(conn, provider=provider)
        ref = service.handle_generate(job)
        change = ChangeRepository(conn).get(ref.id)
        assert "verify_claims" not in provider.stages()
        assert "audit_visible_text" not in provider.stages()
        assert change.status == "ready" and change.validation.can_commit is True

    def test_batching_two_pages_per_three(self, conn):
        slides = plan_slides(4)
        seed_confirmed_plan(conn, slides=slides)
        job = make_generate_job(conn, "job_g10")
        provider = ScriptedProvider(
            {
                "generate_content": [
                    multi_proposal([("ps1", "clm1"), ("ps2", "clm2"), ("ps3", "clm3")]),
                    multi_proposal([("ps4", "clm4")]),
                ],
                "verify_claims": [verdicts("clm1", "clm2", "clm3"), verdicts("clm4")],
                "audit_visible_text": [audit_pass("ps1", "ps2", "ps3"), audit_pass("ps4")],
            }
        )
        service = GenerateService(conn, provider=provider)
        ref = service.handle_generate(job)
        change = ChangeRepository(conn).get(ref.id)
        assert provider.stages().count("generate_content") == 2  # 每批≤3页
        assert len(change.candidate.slides) == 4
        assert change.status == "ready"

    def test_duplicate_claim_ids_across_batches_block(self, conn):
        slides = plan_slides(4)
        seed_confirmed_plan(conn, slides=slides)
        job = make_generate_job(conn, "job_g11")
        provider = ScriptedProvider(
            {
                "generate_content": [
                    # 批1三页含 clmX；批2复用同名 clmX——跨批 id 冲突。
                    multi_proposal([("ps1", "clmX"), ("ps2", "clm2"), ("ps3", "clm3")]),
                    multi_proposal([("ps4", "clmX")]),
                ],
                "verify_claims": [verdicts("clmX", "clm2", "clm3"), verdicts("clmX")],
                "audit_visible_text": [audit_pass("ps1", "ps2", "ps3"), audit_pass("ps4")],
            }
        )
        service = GenerateService(conn, provider=provider)
        ref = service.handle_generate(job)
        change = ChangeRepository(conn).get(ref.id)
        assert change.validation.relations_valid is False
        assert change.status == "blocked"

    def test_fact_referencing_unknown_claim_blocks(self, conn):
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_g12")
        prop = content_proposal()
        prop.slides[0].blocks[0].claim_id = "ghost"
        provider = ScriptedProvider(
            {"generate_content": [prop], "verify_claims": [verdicts("clm1")],
             "audit_visible_text": [audit_pass("ps1")]}
        )
        service = GenerateService(conn, provider=provider)
        ref = service.handle_generate(job)
        change = ChangeRepository(conn).get(ref.id)
        assert change.validation.relations_valid is False
        assert change.status == "blocked"

    def test_cancel_before_model_call(self, conn):
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_g13", cancel=True)
        provider = ScriptedProvider({"generate_content": [content_proposal()]})
        service = GenerateService(conn, provider=provider)
        with pytest.raises(JobCancelled):
            service.handle_generate(job)
        assert provider.calls == []

    def test_expired_deadline_before_model_call(self, conn):
        seed_confirmed_plan(conn)
        past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(
            timespec="seconds"
        )
        job = make_generate_job(conn, "job_g14", deadline_at=past)
        provider = ScriptedProvider({"generate_content": [content_proposal()]})
        service = GenerateService(conn, provider=provider)
        with pytest.raises(ModelTimeout):
            service.handle_generate(job)
        assert provider.calls == []

    def test_llm_calls_accumulated(self, conn):
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_g15")
        provider = ScriptedProvider(
            {"generate_content": [content_proposal()], "verify_claims": [verdicts("clm1")],
             "audit_visible_text": [audit_pass("ps1")]}
        )
        service = GenerateService(conn, provider=provider)
        service.handle_generate(job)
        row = conn.execute(
            "SELECT llm_calls FROM jobs WHERE id='job_g15'"
        ).fetchone()
        # content + verify + audit = 3 次实际请求（循环①新增独立审计通道）。
        assert row["llm_calls"] == 3


def _ready_change_id(conn) -> str:
    """跑一次 happy path 生成，返回 ready 候选 id（commit 测试前置）。"""
    job = make_generate_job(conn, "job_pre")
    provider = ScriptedProvider(
        {"generate_content": [content_proposal()], "verify_claims": [verdicts("clm1")],
         "audit_visible_text": [audit_pass("ps1")]}
    )
    ref = GenerateService(conn, provider=provider).handle_generate(job)
    _insert(conn, "UPDATE projects SET active_job_id=NULL WHERE id='prj1'")
    return ref.id


class TestCommitChange:
    def test_commit_creates_version_and_marks_committed(self, conn):
        seed_confirmed_plan(conn)
        change_id = _ready_change_id(conn)
        service = GenerateService(conn)
        version = service.commit_change(
            "prj1", change_id,
            CommitRequest(base_version=0, corpus_revision=1, acknowledged=True),
        )
        assert version.version == 1
        proj = conn.execute(
            "SELECT current_version FROM projects WHERE id='prj1'"
        ).fetchone()
        assert proj["current_version"] == 1
        got = service.get_change("prj1", change_id)
        assert got.status == "committed"
        n = conn.execute("SELECT COUNT(*) c FROM deck_versions").fetchone()["c"]
        assert n == 1

    def test_blocked_candidate_cannot_commit(self, conn):
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_bl")
        provider = ScriptedProvider(
            {"generate_content": [content_proposal()],
             "verify_claims": [verdicts("clm1", status="unsupported")],
             "audit_visible_text": [audit_pass("ps1")]}
        )
        ref = GenerateService(conn, provider=provider).handle_generate(job)
        _insert(conn, "UPDATE projects SET active_job_id=NULL WHERE id='prj1'")
        service = GenerateService(conn)
        with pytest.raises(ChangeNotCommittable):
            service.commit_change(
                "prj1", ref.id,
                CommitRequest(base_version=0, corpus_revision=1, acknowledged=True),
            )
        assert conn.execute(
            "SELECT COUNT(*) c FROM deck_versions"
        ).fetchone()["c"] == 0

    def test_double_commit_rejected(self, conn):
        seed_confirmed_plan(conn)
        change_id = _ready_change_id(conn)
        service = GenerateService(conn)
        req = CommitRequest(base_version=0, corpus_revision=1, acknowledged=True)
        service.commit_change("prj1", change_id, req)
        with pytest.raises(ChangeNotCommittable):
            service.commit_change("prj1", change_id, req)

    def test_request_base_mismatch_rejected(self, conn):
        seed_confirmed_plan(conn)
        change_id = _ready_change_id(conn)
        service = GenerateService(conn)
        with pytest.raises(VersionConflict):
            service.commit_change(
                "prj1", change_id,
                CommitRequest(base_version=7, corpus_revision=1, acknowledged=True),
            )

    def test_corpus_advanced_marks_stale_on_read(self, conn):
        seed_confirmed_plan(conn)
        change_id = _ready_change_id(conn)
        service = GenerateService(conn)
        # 语料前进：ready 候选按 stale 对待（读路径计算，不写库）。
        _insert(conn, "UPDATE projects SET corpus_revision=2 WHERE id='prj1'")
        got = service.get_change("prj1", change_id)
        assert got.status == "stale"
        with pytest.raises(CorpusChanged):
            service.commit_change(
                "prj1", change_id,
                CommitRequest(base_version=0, corpus_revision=1, acknowledged=True),
            )

    def test_committed_history_never_goes_stale(self, conn):
        # committed 是历史事实：后续版本前进不得把它改写成 stale。
        seed_confirmed_plan(conn)
        change_id = _ready_change_id(conn)
        service = GenerateService(conn)
        service.commit_change(
            "prj1", change_id,
            CommitRequest(base_version=0, corpus_revision=1, acknowledged=True),
        )
        _insert(conn, "UPDATE projects SET current_version=9 WHERE id='prj1'")
        assert service.get_change("prj1", change_id).status == "committed"


class TestReviewClosureT09:
    """T09-Review 阻塞项回归：修复路径同版本落库、重复 verdict 不采信。"""

    def test_repair_proposal_slides_are_the_ones_persisted(self, conn):
        # B1：locator 失败修复后，核验与落库必须用修复后的 proposal——
        # 页面与 claims 必须同一版本，不得"核验A展示B"。
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_b1")
        bad = content_proposal(quote="这段教材里根本没有的话")
        good = content_proposal()
        good.slides[0].title = "NVIC分组（修复后）"
        provider = ScriptedProvider(
            {"generate_content": [bad, good], "verify_claims": [verdicts("clm1")],
             "audit_visible_text": [audit_pass("ps1")]}
        )
        ref = GenerateService(conn, provider=provider).handle_generate(job)
        change = ChangeRepository(conn).get(ref.id)
        assert change.candidate.slides[0].title == "NVIC分组（修复后）"

    def test_duplicate_verdicts_never_greenwash(self, conn):
        # B2：同一 claim 重复答复（首 supported 次 unsupported）=不可信，
        # 必须 not_checked → blocked，不得保留首条过门（docs/05 §8）。
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_b2")
        dup = SemanticVerdicts.model_validate(
            {
                "checks": [
                    {"claim_id": "clm1", "status": "supported", "reason": "首条"},
                    {"claim_id": "clm1", "status": "unsupported", "reason": "次条"},
                ],
                "unbound_assertions": [],
            }
        )
        provider = ScriptedProvider(
            {"generate_content": [content_proposal()], "verify_claims": [dup],
             "audit_visible_text": [audit_pass("ps1")]}
        )
        ref = GenerateService(conn, provider=provider).handle_generate(job)
        change = ChangeRepository(conn).get(ref.id)
        assert change.validation.claim_checks[0].semantic_status == "not_checked"
        assert change.status == "blocked"

    def test_slide_id_set_must_equal_plan_ids(self, conn):
        # N2：模型偷换/增删页 id（计划外页面）→ layout_valid=False → blocked。
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_n2")
        prop = content_proposal()
        prop.slides[0].id = "ps999"
        provider = ScriptedProvider(
            {"generate_content": [prop], "verify_claims": [verdicts("clm1")],
             "audit_visible_text": [audit_pass("ps999")]}
        )
        ref = GenerateService(conn, provider=provider).handle_generate(job)
        change = ChangeRepository(conn).get(ref.id)
        assert change.validation.layout_valid is False
        assert change.status == "blocked"

    def test_model_overflow_pages_fails_typed_not_internal(self, conn):
        # N3：跨批累加越出 DeckSpec 边界（>16页）→ typed ModelOutputInvalid
        # （job failed MODEL_OUTPUT_INVALID），不得裸 ValidationError→INTERNAL_ERROR。
        from courseware_core.errors import ModelOutputInvalid

        slides = plan_slides(12)
        seed_confirmed_plan(conn, slides=slides)
        job = make_generate_job(conn, "job_n3")

        def fat(prefix):
            return multi_proposal([(f"{prefix}s{i}", f"{prefix}c{i}") for i in range(16)])

        props = [fat(f"b{k}") for k in range(4)]
        vers = [verdicts(*[f"b{k}c{i}" for i in range(16)]) for k in range(4)]
        audits = [
            audit_pass(*[f"b{k}s{i}" for i in range(16)]) for k in range(4)
        ]
        provider = ScriptedProvider(
            {"generate_content": props, "verify_claims": vers,
             "audit_visible_text": audits}
        )
        with pytest.raises(ModelOutputInvalid):
            GenerateService(conn, provider=provider).handle_generate(job)


class TestCommitConcurrency:
    def test_concurrent_commit_same_change_exactly_one_wins(self, conn, tmp_path):
        # Barrier 竞态：两连接同时 commit 同一候选，恰一方成功、版本恰一行。
        import threading

        seed_confirmed_plan(conn)
        change_id = _ready_change_id(conn)
        db = tmp_path / "race_commit.db"
        seed = connect(db)
        from courseware_core.storage.database import init_db

        init_db(seed)
        tables = ("projects", "materials", "chunks", "plans", "jobs",
                  "deck_versions", "artifacts", "idempotency_keys", "changes")
        for table in tables:
            rows = conn.execute("SELECT * FROM " + table).fetchall()
            cols = [d[0] for d in conn.execute(
                "SELECT * FROM " + table + " LIMIT 0").description]
            with seed:
                for r in rows:
                    marks = ",".join("?" * len(cols))
                    seed.execute(
                        "INSERT INTO " + table + " (" + ",".join(cols) + ")"
                        " VALUES (" + marks + ")",
                        tuple(r),
                    )
        seed.close()

        barrier = threading.Barrier(2)
        outcomes: list = []

        def grab():
            c = connect(db)
            try:
                svc = GenerateService(c)
                barrier.wait(timeout=10)
                try:
                    v = svc.commit_change(
                        "prj1", change_id,
                        CommitRequest(base_version=0, corpus_revision=1, acknowledged=True),
                    )
                    outcomes.append(("ok", v.version))
                except DomainError as exc:
                    outcomes.append(("rejected", exc.code))
            finally:
                c.close()

        threads = [threading.Thread(target=grab) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        oks = [o for o in outcomes if o[0] == "ok"]
        assert len(oks) == 1, "恰有一方提交成功，实际 " + str(outcomes)
        c = connect(db)
        try:
            assert c.execute("SELECT COUNT(*) c FROM deck_versions").fetchone()["c"] == 1
            assert c.execute(
                "SELECT status FROM changes WHERE id=?", (change_id,)
            ).fetchone()["status"] == "committed"
        finally:
            c.close()


# ---------- 循环①（Q01）：可见文字审计独立化 + missing_evidence 门 + verdict 严格双射 ----------


def teaching_proposal(slide_id="ps1", layout="concept",
                      text="抢占优先级数值越小越优先，同组抢占位无效。"):
    """零 claim、专业事实全部写在 teaching.text 里的提案——正是"改名逃逸"形态。"""
    return ContentProposal.model_validate(
        {
            "claims": [],
            "slides": [{"id": slide_id, "title": "抢占与同组", "layout": layout,
                        "blocks": [{"type": "teaching", "text": text}]}],
            "missing_evidence": [],
        }
    )


def illustration_proposal(slide_id="ps1",
                          assumption="假设教室开发板为F103系列（课堂假设，非实测）。"):
    return ContentProposal.model_validate(
        {
            "claims": [],
            "slides": [{"id": slide_id, "title": "课堂演示", "layout": "concept",
                        "blocks": [{"type": "illustration", "text": "演示分组配置",
                                     "assumptions": [assumption]}]}],
            "missing_evidence": [],
        }
    )


def audit_pass(*slide_ids):
    return VisibleTextAudit.model_validate(
        {"audited_slide_ids": list(slide_ids), "unbound_assertions": []}
    )


def audit_unbound(slide_ids, unbound):
    return VisibleTextAudit.model_validate(
        {"audited_slide_ids": list(slide_ids), "unbound_assertions": unbound}
    )


class TestVisibleTextAuditGate:
    def test_zero_claim_teaching_page_must_be_audited_and_blocked(self, conn):
        # claims=[] + 模型把专业事实写进 teaching：不得因 claim_checks 为空自动盖绿。
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_a1")
        provider = ScriptedProvider(
            {"generate_content": [teaching_proposal()],
             "audit_visible_text": [audit_unbound(["ps1"], UNBOUND)]}
        )
        service = GenerateService(conn, provider=provider)
        ref = service.handle_generate(job)
        change = ChangeRepository(conn).get(ref.id)
        assert "audit_visible_text" in provider.stages()
        assert change.status == "blocked"
        assert change.validation.can_commit is False
        assert len(change.validation.unbound_assertions) == 1

    def test_zero_claim_clean_audit_passes_and_audit_called(self, conn):
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_a2")
        provider = ScriptedProvider(
            {"generate_content": [teaching_proposal()],
             "audit_visible_text": [audit_pass("ps1")]}
        )
        service = GenerateService(conn, provider=provider)
        ref = service.handle_generate(job)
        change = ChangeRepository(conn).get(ref.id)
        assert "audit_visible_text" in provider.stages()
        assert change.status == "ready" and change.validation.can_commit is True

    def test_plan_title_cover_exempt_no_audit_call(self, conn):
        # 教师确认计划里的 title 页=合法静态封面，豁免可见文字审计（不误伤）。
        seed_confirmed_plan(conn, slides=plan_slides(1, layout="title"))
        job = make_generate_job(conn, "job_a3")
        provider = ScriptedProvider(
            {"generate_content": [teaching_proposal(layout="title")]}
        )
        service = GenerateService(conn, provider=provider)
        ref = service.handle_generate(job)
        change = ChangeRepository(conn).get(ref.id)
        assert "audit_visible_text" not in provider.stages()
        assert "verify_claims" not in provider.stages()
        assert change.status == "ready"

    def test_model_self_reported_title_not_exempt_when_plan_concept(self, conn):
        # 豁免判据是教师计划的 layout，不是模型自报：plan=concept 页模型自称
        # title 也不得绕过可见文字审计。
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_a4")
        provider = ScriptedProvider(
            {"generate_content": [teaching_proposal(layout="title")],
             "audit_visible_text": [audit_pass("ps1")]}
        )
        service = GenerateService(conn, provider=provider)
        service.handle_generate(job)
        assert "audit_visible_text" in provider.stages()

    def test_assumptions_text_included_in_audit_input(self, conn):
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_a5")
        assumption = "假设教室开发板为F103系列（课堂假设，非实测）。"
        provider = ScriptedProvider(
            {"generate_content": [illustration_proposal(assumption=assumption)],
             "audit_visible_text": [audit_pass("ps1")]}
        )
        service = GenerateService(conn, provider=provider)
        service.handle_generate(job)
        audit_call = next(c for c in provider.calls
                          if c["stage"] == "audit_visible_text")
        user_msg = audit_call["messages"][-1]["content"]
        assert assumption in user_msg

    def test_audit_missing_coverage_blocks(self, conn):
        # 模型漏审（audited 集合不含必审页）=该批可见文字未经审计，不得盖绿。
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_a6")
        provider = ScriptedProvider(
            {"generate_content": [teaching_proposal()],
             "audit_visible_text": [audit_pass()]}
        )
        service = GenerateService(conn, provider=provider)
        ref = service.handle_generate(job)
        change = ChangeRepository(conn).get(ref.id)
        assert change.status == "blocked"
        assert change.validation.can_commit is False

    def test_audit_unknown_slide_id_blocks(self, conn):
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_a7")
        provider = ScriptedProvider(
            {"generate_content": [teaching_proposal()],
             "audit_visible_text": [audit_pass("ps999")]}
        )
        service = GenerateService(conn, provider=provider)
        ref = service.handle_generate(job)
        assert ChangeRepository(conn).get(ref.id).status == "blocked"

    def test_audit_duplicate_slide_ids_blocks(self, conn):
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_a8")
        provider = ScriptedProvider(
            {"generate_content": [teaching_proposal()],
             "audit_visible_text": [VisibleTextAudit.model_validate(
                 {"audited_slide_ids": ["ps1", "ps1"], "unbound_assertions": []})]}
        )
        service = GenerateService(conn, provider=provider)
        ref = service.handle_generate(job)
        assert ChangeRepository(conn).get(ref.id).status == "blocked"

    def test_fact_batch_also_audited_after_verify(self, conn):
        # 有 claim 的批同样要有独立可见文字审计通道（与 claim 核验分离）。
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_a9")
        provider = ScriptedProvider(
            {"generate_content": [content_proposal()],
             "verify_claims": [verdicts("clm1")],
             "audit_visible_text": [audit_pass("ps1")]}
        )
        service = GenerateService(conn, provider=provider)
        ref = service.handle_generate(job)
        stages = provider.stages()
        assert stages.index("verify_claims") < stages.index("audit_visible_text")
        assert ChangeRepository(conn).get(ref.id).status == "ready"

    def test_missing_evidence_nonempty_blocks(self, conn):
        # P0 保守门：missing_evidence 非空=模型自认有内容缺依据，不得只记
        # warning 放行（AGENT_00-Q06；放宽此策略须先写 ADR）。
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_a10")
        prop = content_proposal()
        prop.missing_evidence = ["同组优先级行为缺少资料支持，未生成对应内容。"]
        provider = ScriptedProvider(
            {"generate_content": [prop],
             "verify_claims": [verdicts("clm1")],
             "audit_visible_text": [audit_pass("ps1")]}
        )
        service = GenerateService(conn, provider=provider)
        ref = service.handle_generate(job)
        change = ChangeRepository(conn).get(ref.id)
        assert change.status == "blocked"
        assert change.validation.can_commit is False

    def test_missing_evidence_late_batch_still_blocks(self, conn):
        # 多批聚合：仅第二批 missing_evidence 非空也必须整候选 blocked
        # （门是"任一批"，不是"首批"）。
        slides = plan_slides(4)
        seed_confirmed_plan(conn, slides=slides)
        job = make_generate_job(conn, "job_a10b")
        first = multi_proposal([("ps1", "clm1"), ("ps2", "clm2"), ("ps3", "clm3")])
        second = multi_proposal([("ps4", "clm4")])
        second.missing_evidence = ["第四页部分内容缺资料支持。"]
        provider = ScriptedProvider(
            {
                "generate_content": [first, second],
                "verify_claims": [verdicts("clm1", "clm2", "clm3"), verdicts("clm4")],
                "audit_visible_text": [
                    audit_pass("ps1", "ps2", "ps3"), audit_pass("ps4")
                ],
            }
        )
        ref = GenerateService(conn, provider=provider).handle_generate(job)
        change = ChangeRepository(conn).get(ref.id)
        assert change.status == "blocked"
        assert change.validation.can_commit is False

    def test_verdict_extra_unknown_id_blocks_batch(self, conn):
        # 严格双射：预期 claim 集合必须与 verdict 集合恰好一致。模型造新 ID
        # （clm1 也在）说明答复失控，整批核验不可信 → 全部 not_checked → blocked。
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_a11")
        provider = ScriptedProvider(
            {"generate_content": [content_proposal()],
             "verify_claims": [verdicts("clm1", "ghost")],
             "audit_visible_text": [audit_pass("ps1")]}
        )
        service = GenerateService(conn, provider=provider)
        ref = service.handle_generate(job)
        change = ChangeRepository(conn).get(ref.id)
        assert change.status == "blocked"
        assert change.validation.claim_checks[0].semantic_status == "not_checked"


# ---------- 循环②（Q02/Q04/Q05）：提案/存储类型隔离 + 本批 allowed 集合 ----------


def _illustration_payload(evidence_refs):
    return {
        "claims": [],
        "slides": [{
            "id": "ps1", "title": "课堂演示", "layout": "concept",
            "blocks": [{"type": "illustration", "text": "演示分组配置",
                        "assumptions": ["课堂假设，非实测。"],
                        "evidence_refs": evidence_refs}],
        }],
        "missing_evidence": [],
    }


def seed_offtopic_chunk(conn):
    """项目里存在、但检索不会命中（不进本批 prompt）的片段。"""
    text = "自行车传动系统由牙盘、飞轮和链条组成，定期上油可延长寿命。"
    _insert(
        conn,
        "INSERT INTO chunks (chunk_id, project_id, document_id, corpus_revision,"
        " pdf_page, page_start, page_end, text, text_sha256, extractor_version,"
        " tokenizer_version) VALUES ('chk_off','prj1','mat1',1,1,0,?,?,?,"
        " 'pypdf-5.9.0-nfc-v1','jieba-0.42.1+ascii-v1')",
        len(text), text, hashlib.sha256(text.encode()).hexdigest(),
    )


class TestProposalStorageSplit:
    def test_model_cannot_forge_span_authority_fields(self, conn):
        # 提案引用只允许 chunk_id+quote；模型带 document_id/pdf_page/start/end
        # 必须在 Schema 层直接拒绝（提案/存储类型隔离，AGENT_00-Q04）。
        from pydantic import ValidationError

        payload = _illustration_payload([
            {"chunk_id": "chk1", "quote": QUOTE1, "document_id": "evil",
             "pdf_page": 99, "start": 0, "end": 5},
        ])
        with pytest.raises(ValidationError):
            ContentProposal.model_validate(payload)

    def test_illustration_refs_resolved_server_side(self, conn):
        # 合法提案形态（chunk_id+quote）→ 权威字段全部由服务端解析填充。
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_b1a")
        prop = ContentProposal.model_validate(
            _illustration_payload([{"chunk_id": "chk1", "quote": QUOTE1}])
        )
        provider = ScriptedProvider(
            {"generate_content": [prop], "audit_visible_text": [audit_pass("ps1")]}
        )
        ref = GenerateService(conn, provider=provider).handle_generate(job)
        change = ChangeRepository(conn).get(ref.id)
        assert change.status == "ready"
        block = change.candidate.slides[0].blocks[0]
        span = block.evidence_refs[0]
        assert span.document_id == "mat1" and span.pdf_page == 1
        assert CHUNK1_TEXT[span.start:span.end] == span.quote == QUOTE1

    def test_illustration_bad_reference_blocks_and_no_forged_span(self, conn):
        # illustration 引用定位失败（假 quote）：修复仍失败 → blocked，
        # 失败引用不得进入候选来源（宁可空 refs+报告，不存可疑来源）。
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_b1b")
        bad = ContentProposal.model_validate(
            _illustration_payload([{"chunk_id": "chk1", "quote": "教材里不存在的话"}])
        )
        provider = ScriptedProvider(
            {"generate_content": [bad, bad], "audit_visible_text": [audit_pass("ps1")]}
        )
        ref = GenerateService(conn, provider=provider).handle_generate(job)
        change = ChangeRepository(conn).get(ref.id)
        assert change.status == "blocked"
        assert change.validation.can_commit is False
        block = change.candidate.slides[0].blocks[0]
        assert all(s.quote != "教材里不存在的话" for s in block.evidence_refs)

    def test_claim_chunk_not_in_batch_prompt_rejected(self, conn):
        # 同项目存在但本批未进 prompt 的 chunk 不得被 claim 引用（防"偷看"
        # 项目里模型没见到的内容，AGENT_00-Q05）。
        seed_confirmed_plan(conn)
        seed_offtopic_chunk(conn)
        job = make_generate_job(conn, "job_b2a")
        prop = content_proposal(chunk_id="chk_off",
                                quote="自行车传动系统由牙盘、飞轮和链条组成")
        provider = ScriptedProvider(
            {"generate_content": [prop, prop],
             "verify_claims": [verdicts("clm1")],
             "audit_visible_text": [audit_pass("ps1")]}
        )
        ref = GenerateService(conn, provider=provider).handle_generate(job)
        change = ChangeRepository(conn).get(ref.id)
        assert change.status == "blocked"
        check = change.validation.claim_checks[0]
        assert check.locator_status == "invalid"

    def test_illustration_chunk_not_in_batch_prompt_rejected(self, conn):
        seed_confirmed_plan(conn)
        seed_offtopic_chunk(conn)
        job = make_generate_job(conn, "job_b2b")
        prop = ContentProposal.model_validate(
            _illustration_payload(
                [{"chunk_id": "chk_off", "quote": "定期上油可延长寿命。"}]
            )
        )
        provider = ScriptedProvider(
            {"generate_content": [prop, prop],
             "audit_visible_text": [audit_pass("ps1")]}
        )
        ref = GenerateService(conn, provider=provider).handle_generate(job)
        change = ChangeRepository(conn).get(ref.id)
        assert change.status == "blocked"
        block = change.candidate.slides[0].blocks[0]
        assert block.evidence_refs == []


# ---------- 循环③（Q07）：教师确认顺序与布局保护 ----------


class TestPlanOrderAndLayoutProtected:
    def test_slide_order_normalized_to_plan(self, conn):
        # 模型只是顺序返回不同：服务器按教师确认计划确定性重排（不浪费一次
        # 模型调用），落库顺序与 affected_slide_ids 都必须是计划顺序。
        slides = plan_slides(3)
        seed_confirmed_plan(conn, slides=slides)
        job = make_generate_job(conn, "job_c1")
        provider = ScriptedProvider(
            {
                "generate_content": [
                    multi_proposal([("ps3", "clm3"), ("ps1", "clm1"), ("ps2", "clm2")])
                ],
                "verify_claims": [verdicts("clm1", "clm2", "clm3")],
                "audit_visible_text": [audit_pass("ps1", "ps2", "ps3")],
            }
        )
        ref = GenerateService(conn, provider=provider).handle_generate(job)
        change = ChangeRepository(conn).get(ref.id)
        assert [s.id for s in change.candidate.slides] == ["ps1", "ps2", "ps3"]
        assert change.affected_slide_ids == ["ps1", "ps2", "ps3"]
        assert change.status == "ready"

    def test_layout_mismatch_blocks(self, conn):
        # 布局是教师确认大纲的一部分：模型偷改 layout → layout_valid=False →
        # blocked，不得"悄悄改课"。
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_c2")
        prop = content_proposal()
        prop.slides[0].layout = "two_column"
        provider = ScriptedProvider(
            {"generate_content": [prop],
             "verify_claims": [verdicts("clm1")],
             "audit_visible_text": [audit_pass("ps1")]}
        )
        ref = GenerateService(conn, provider=provider).handle_generate(job)
        change = ChangeRepository(conn).get(ref.id)
        assert change.validation.layout_valid is False
        assert change.status == "blocked"
        assert change.validation.can_commit is False

    def test_reordered_output_still_verifies_and_audits_normally(self, conn):
        # 重排只动页顺序：核验与落库内容仍是修复后 proposal（B1 语义不回退）。
        slides = plan_slides(2)
        seed_confirmed_plan(conn, slides=slides)
        job = make_generate_job(conn, "job_c3")
        p2 = multi_proposal([("ps2", "clm2")])
        p1 = multi_proposal([("ps1", "clm1")])
        merged = ContentProposal.model_validate(
            {
                "claims": [c.model_dump(mode="json") for c in p2.claims + p1.claims],
                "slides": [s.model_dump(mode="json") for s in p2.slides + p1.slides],
                "missing_evidence": [],
            }
        )
        provider = ScriptedProvider(
            {"generate_content": [merged],
             "verify_claims": [verdicts("clm1", "clm2")],
             "audit_visible_text": [audit_pass("ps1", "ps2")]}
        )
        ref = GenerateService(conn, provider=provider).handle_generate(job)
        change = ChangeRepository(conn).get(ref.id)
        assert [s.id for s in change.candidate.slides] == ["ps1", "ps2"]
        assert {c.claim_id for c in change.validation.claim_checks} == {"clm1", "clm2"}
        assert change.status == "ready"


# ---------- 循环④（Q08）：候选写库前执行态守卫 ----------


class TestCandidateWriteGuard:
    def test_cancel_after_last_call_before_write_produces_no_candidate(self, conn):
        # 取消发生在"最后一次核验完成 → 写候选"之间：不得留下可被应用的
        # ready 孤儿候选（AGENT_00-Q08：不能只依赖 worker publish 阶段复核）。
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_d1")

        def cancel_then_audit(context):
            _insert(
                conn, "UPDATE jobs SET cancel_requested=1 WHERE id='job_d1'"
            )
            return audit_pass("ps1")

        provider = ScriptedProvider(
            {"generate_content": [content_proposal()],
             "verify_claims": [verdicts("clm1")],
             "audit_visible_text": [cancel_then_audit]}
        )
        service = GenerateService(conn, provider=provider)
        with pytest.raises(JobCancelled):
            service.handle_generate(job)
        n = conn.execute("SELECT COUNT(*) c FROM changes").fetchone()["c"]
        assert n == 0, "取消后产生的候选不得写入 changes 表"
        # 取消不丢成本记录：finally 累计语义保持（Review N6）。
        row = conn.execute(
            "SELECT llm_calls FROM jobs WHERE id='job_d1'"
        ).fetchone()
        assert row["llm_calls"] == 3

    def test_deadline_exceeded_before_write_produces_no_candidate(self, conn):
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_d2")

        def expire_then_audit(context):
            context.deadline = time.monotonic() - 1
            return audit_pass("ps1")

        provider = ScriptedProvider(
            {"generate_content": [content_proposal()],
             "verify_claims": [verdicts("clm1")],
             "audit_visible_text": [expire_then_audit]}
        )
        service = GenerateService(conn, provider=provider)
        with pytest.raises(ModelTimeout):
            service.handle_generate(job)
        n = conn.execute("SELECT COUNT(*) c FROM changes").fetchone()["c"]
        assert n == 0

    def test_interrupted_job_state_blocks_write(self, conn):
        # 执行有效性：job 行被外部改为非 running（如崩溃恢复标 interrupted）
        # 时，handler 收尾不得再写候选。
        seed_confirmed_plan(conn)
        job = make_generate_job(conn, "job_d3")

        def interrupt_then_audit(context):
            _insert(conn, "UPDATE jobs SET status='interrupted' WHERE id='job_d3'")
            return audit_pass("ps1")

        provider = ScriptedProvider(
            {"generate_content": [content_proposal()],
             "verify_claims": [verdicts("clm1")],
             "audit_visible_text": [interrupt_then_audit]}
        )
        service = GenerateService(conn, provider=provider)
        with pytest.raises(JobCancelled):
            service.handle_generate(job)
        n = conn.execute("SELECT COUNT(*) c FROM changes").fetchone()["c"]
        assert n == 0
