"""T09 generations 受理路由契约 + 生成端到端（worker+ScriptedProvider，零真实模型）。"""

import hashlib
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from courseware_core.llm.adapter import TypedCompletion, Usage
from courseware_core.models import ContentProposal, Job, PlanProposal, SemanticVerdicts
from courseware_core.storage.database import connect

CHUNK1_TEXT = "讲解：NVIC优先级分组通过AIRCR配置，需要先解锁KEYR。"
CHUNK2_TEXT = "补充：NVIC优先级分组通过AIRCR配置组设置抢占与响应优先级。"
QUOTE1 = "NVIC优先级分组通过AIRCR配置"

PROJECT_BODY = {
    "course": {
        "topic": "STM32 中断",
        "audience": "大二",
        "duration_minutes": 45,
        "goals": ["NVIC优先级分组通过AIRCR配置"],
        "target_slides": 8,
    },
    "consent_to_cloud_processing": True,
}


class StageProvider:
    """按 stage 脚本队列；plan 阶段动态取真实 chunk_id（端到端引用可解析）。"""

    def __init__(self, plan_value):
        self._plan_value = plan_value
        self._queues: dict[str, list] = {}
        self.calls: list[str] = []

    def queue(self, stage, values):
        self._queues[stage] = list(values)

    def complete_json(self, stage, schema_name, messages, context):
        self.calls.append(stage)
        context.budget.consume(1)
        if stage == "plan_course":
            value = self._plan_value
        else:
            queue = self._queues.get(stage)
            if not queue:
                raise AssertionError(f"no scripted response for stage={stage}")
            value = queue.pop(0)
        return TypedCompletion(
            value=value, usage=Usage(10, 5, 15),
            provider_request_id=f"fake-{len(self.calls)}", attempts=1,
        )


def plan_proposal() -> PlanProposal:
    return PlanProposal.model_validate(
        {
            "slides": [
                {"id": "ps1", "title": "NVIC优先级分组", "purpose": "讲解AIRCR配置",
                 "layout": "concept", "goal_indices": [0],
                 "evidence_chunk_ids": ["chk_direct"]},
            ],
            "coverage_notes": [
                {"goal_index": 0, "candidate_chunk_ids": ["chk_direct"], "note": "有支持"},
            ],
        }
    )


def content_proposal(chunk_id: str = "chk_seed") -> ContentProposal:
    return ContentProposal.model_validate(
        {
            "claims": [
                {"id": "clm1", "text": "NVIC优先级分组通过AIRCR配置。", "kind": "direct",
                 "evidence_refs": [{"chunk_id": chunk_id, "quote": QUOTE1}],
                 "rationale": None},
            ],
            "slides": [
                {"id": "ps1", "title": "NVIC分组", "layout": "concept",
                 "blocks": [{"type": "fact", "claim_id": "clm1"}]},
            ],
            "missing_evidence": [],
        }
    )


def verdicts_supported() -> SemanticVerdicts:
    return SemanticVerdicts.model_validate(
        {
            "checks": [{"claim_id": "clm1", "status": "supported", "reason": "原文支持。"}],
            "unbound_assertions": [],
        }
    )


def seed_ready_project(client, conn):
    r = client.post(
        "/api/v1/projects", json=PROJECT_BODY, headers={"Idempotency-Key": "k-seed-g"}
    )
    assert r.status_code == 201
    project_id = r.json()["id"]
    sha1 = hashlib.sha256(CHUNK1_TEXT.encode()).hexdigest()
    sha2 = hashlib.sha256(CHUNK2_TEXT.encode()).hexdigest()
    with conn:
        conn.execute(
            "INSERT INTO materials (id, project_id, original_name, sha256, status,"
            " pdf_pages, usable_pages, corpus_revision, warnings_json, error_code,"
            " file_path, file_size, job_id, created_at, updated_at)"
            " VALUES ('mat_seed', ?, 'x.pdf', ?, 'ready', 1, 1, 1, '[]', NULL,"
            " 'x.pdf', 100, NULL, '2026-09-19T00:00:00+00:00', '2026-09-19T00:00:00+00:00')",
            (project_id, "a" * 64),
        )
        for cid, text, sha in (("chk_seed", CHUNK1_TEXT, sha1), ("chk_seed2", CHUNK2_TEXT, sha2)):
            conn.execute(
                "INSERT INTO chunks (chunk_id, project_id, document_id, corpus_revision,"
                " pdf_page, page_start, page_end, text, text_sha256, extractor_version,"
                " tokenizer_version) VALUES (?, ?, 'mat_seed', 1, 1, 0, ?, ?, ?,"
                " 'pypdf-5.9.0-nfc-v1', 'jieba-0.42.1+ascii-v1')",
                (cid, project_id, len(text), text, sha),
            )
        conn.execute(
            "UPDATE projects SET corpus_revision = 1 WHERE id = ?", (project_id,)
        )
    return project_id


def seed_plan_row(conn, project_id, *, status="confirmed", plan_id="plan_g"):
    plan_json = {
        "id": plan_id, "project_id": project_id, "corpus_revision": 1, "status": status,
        "coverage": [{"goal_index": 0, "status": "supported",
                      "chunk_ids": ["chk_seed", "chk_seed2"], "note": ""}],
        "slides": [
            {"id": "ps1", "title": "NVIC优先级分组", "purpose": "讲解AIRCR配置",
             "layout": "concept", "goal_indices": [0], "evidence_chunk_ids": ["chk_seed"]},
        ],
        "accepted_goal_indices": [0],
        "created_at": "2026-09-19T00:00:00+00:00",
    }
    with conn:
        conn.execute(
            "INSERT INTO plans (id, project_id, corpus_revision, status, plan_json,"
            " created_at, updated_at) VALUES (?, ?, 1, ?, ?, '2026-09-19T00:00:00+00:00',"
            " '2026-09-19T00:00:00+00:00')",
            (plan_id, project_id, status, json.dumps(plan_json, ensure_ascii=False)),
        )
    return plan_id


def app_client(db_path, handlers=None):
    from courseware_api.main import create_app

    app = create_app(db_path, worker_handlers=handlers)
    return TestClient(app)


GEN_BODY = {"plan_id": "plan_g", "base_version": 0, "corpus_revision": 1}


class TestGenerateRoutes:
    def test_post_generations_202_and_holds_lock(self, tmp_path):
        db = tmp_path / "a.db"
        client = app_client(db)
        conn = connect(db)
        with client:
            pid = seed_ready_project(client, conn)
            seed_plan_row(conn, pid)
            r = client.post(
                f"/api/v1/projects/{pid}/generations", json=GEN_BODY,
                headers={"Idempotency-Key": "k-gen-1"},
            )
            assert r.status_code == 202
            job_id = r.json()["job_id"]
            row = conn.execute(
                "SELECT kind, status, params_json FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            assert row["kind"] == "generate" and row["status"] == "queued"
            proj = conn.execute(
                "SELECT active_job_id FROM projects WHERE id = ?", (pid,)
            ).fetchone()
            assert proj["active_job_id"] == job_id
        conn.close()

    def test_idempotent_replay_single_job(self, tmp_path):
        db = tmp_path / "b.db"
        client = app_client(db)
        conn = connect(db)
        with client:
            pid = seed_ready_project(client, conn)
            seed_plan_row(conn, pid)
            body = {"Idempotency-Key": "k-gen-2"}
            r1 = client.post(f"/api/v1/projects/{pid}/generations", json=GEN_BODY, headers=body)
            r2 = client.post(f"/api/v1/projects/{pid}/generations", json=GEN_BODY, headers=body)
            assert r1.status_code == r2.status_code == 202
            assert r1.json() == r2.json()
            n = conn.execute("SELECT COUNT(*) c FROM jobs WHERE kind='generate'").fetchone()["c"]
            assert n == 1
        conn.close()

    def test_crash_after_commit_recovers_same_job(self, tmp_path):
        # R00-D 锚点语义在 generate 受理同样成立（业务已提交响应未缓存）。
        db = tmp_path / "c.db"
        client = app_client(db)
        conn = connect(db)
        with client:
            pid = seed_ready_project(client, conn)
            seed_plan_row(conn, pid)
            headers = {"Idempotency-Key": "k-gen-crash"}
            r1 = client.post(f"/api/v1/projects/{pid}/generations", json=GEN_BODY, headers=headers)
            job_id = r1.json()["job_id"]
            with conn:
                conn.execute(
                    "UPDATE idempotency_keys SET response_status=-1, response_body='null'"
                    " WHERE idem_key='k-gen-crash'"
                )
            r2 = client.post(f"/api/v1/projects/{pid}/generations", json=GEN_BODY, headers=headers)
            assert r2.status_code == 202
            assert r2.json()["job_id"] == job_id
            n = conn.execute("SELECT COUNT(*) c FROM jobs WHERE kind='generate'").fetchone()["c"]
            assert n == 1
        conn.close()

    def test_unconfirmed_plan_409(self, tmp_path):
        db = tmp_path / "d.db"
        client = app_client(db)
        conn = connect(db)
        with client:
            pid = seed_ready_project(client, conn)
            seed_plan_row(conn, pid, status="draft")
            r = client.post(
                f"/api/v1/projects/{pid}/generations", json=GEN_BODY,
                headers={"Idempotency-Key": "k-gen-4"},
            )
            assert r.status_code == 409
            assert r.json()["error"]["code"] == "PLAN_NOT_CONFIRMED"
        conn.close()

    def test_consent_required_409(self, tmp_path):
        db = tmp_path / "e.db"
        client = app_client(db)
        conn = connect(db)
        with client:
            body = dict(PROJECT_BODY, consent_to_cloud_processing=False)
            r = client.post("/api/v1/projects", json=body, headers={"Idempotency-Key": "k-e"})
            pid = r.json()["id"]
            seed_plan_row(conn, pid)
            r = client.post(
                f"/api/v1/projects/{pid}/generations", json=GEN_BODY,
                headers={"Idempotency-Key": "k-gen-5"},
            )
            assert r.status_code == 409
            assert r.json()["error"]["code"] == "CONSENT_REQUIRED"
        conn.close()

    def test_base_version_mismatch_409(self, tmp_path):
        db = tmp_path / "f.db"
        client = app_client(db)
        conn = connect(db)
        with client:
            pid = seed_ready_project(client, conn)
            seed_plan_row(conn, pid)
            r = client.post(
                f"/api/v1/projects/{pid}/generations",
                json=dict(GEN_BODY, base_version=3),
                headers={"Idempotency-Key": "k-gen-6"},
            )
            assert r.status_code == 409
            assert r.json()["error"]["code"] == "VERSION_CONFLICT"
        conn.close()

    def test_busy_project_409(self, tmp_path):
        db = tmp_path / "g.db"
        client = app_client(db)
        conn = connect(db)
        with client:
            pid = seed_ready_project(client, conn)
            seed_plan_row(conn, pid)
            with conn:
                conn.execute(
                    "UPDATE projects SET active_job_id='job_locked' WHERE id=?", (pid,)
                )
            r = client.post(
                f"/api/v1/projects/{pid}/generations", json=GEN_BODY,
                headers={"Idempotency-Key": "k-gen-7"},
            )
            assert r.status_code == 409
            assert r.json()["error"]["code"] == "PROJECT_BUSY"
        conn.close()


class TestGenerateEndToEnd:
    def test_confirm_then_generate_produces_ready_change(self, tmp_path):
        from courseware_api.wiring import build_worker_handlers

        db_path = tmp_path / "e2e" / "app.db"
        provider = StageProvider(plan_proposal())
        provider.queue("generate_content", [content_proposal()])
        provider.queue("verify_claims", [verdicts_supported()])

        def plan_handler(job: Job):
            from courseware_core.services.plan_service import PlanService

            c = connect(db_path)
            try:
                return PlanService(c, provider=provider).handle_plan(job)
            finally:
                c.close()

        def generate_handler(job: Job):
            from courseware_core.services.generate_service import GenerateService

            c = connect(db_path)
            try:
                return GenerateService(c, provider=provider).handle_generate(job)
            finally:
                c.close()

        handlers = build_worker_handlers(db_path, tmp_path / "e2e" / "materials")
        handlers["plan"] = plan_handler
        handlers["generate"] = generate_handler
        client = app_client(db_path, handlers)
        with client:
            r = client.post(
                "/api/v1/projects", json=PROJECT_BODY, headers={"Idempotency-Key": "e1"}
            )
            pid = r.json()["id"]
            # 直接种 ready 语料（真实 parse 链路在 T05 e2e 已覆盖，这里聚焦生成）。
            conn = connect(db_path)
            try:
                seed_chunks_direct(conn, pid)
            finally:
                conn.close()
            r = client.post(
                f"/api/v1/projects/{pid}/plans", json={"corpus_revision": 1},
                headers={"Idempotency-Key": "e3"},
            )
            assert r.status_code == 202
            plan_id = poll_plan_id(client, r.json()["job_id"])
            r = client.post(
                f"/api/v1/projects/{pid}/plans/{plan_id}/confirm",
                json={
                    "corpus_revision": 1,
                    "slides": [
                        {"id": "ps1", "title": "NVIC优先级分组", "purpose": "讲解AIRCR配置",
                         "layout": "concept", "goal_indices": [0],
                         "evidence_chunk_ids": ["chk_direct"]},
                    ],
                    "accepted_goal_indices": [0],
                    "acknowledged": True,
                },
                headers={"Idempotency-Key": "e4"},
            )
            assert r.status_code == 200
            provider.queue("generate_content", [content_proposal("chk_direct")])
            r = client.post(
                f"/api/v1/projects/{pid}/generations",
                json={"plan_id": plan_id, "base_version": 0, "corpus_revision": 1},
                headers={"Idempotency-Key": "e5"},
            )
            assert r.status_code == 202
            job = poll_job(client, r.json()["job_id"])
            assert job["status"] == "succeeded"
            assert job["result_ref"]["type"] == "change"
            r = client.get(f"/api/v1/projects/{pid}/changes/{job['result_ref']['id']}")
            assert r.status_code == 200
            change = r.json()
            assert change["status"] == "ready"
            assert change["validation"]["can_commit"] is True
            assert change["candidate"]["claims"][0]["evidence_refs"][0]["chunk_id"] == "chk_direct"
            assert "plan_course" in provider.calls
            assert provider.calls.count("generate_content") == 1
            assert provider.calls.count("verify_claims") == 1


def seed_chunks_direct(conn, project_id):
    sha1 = hashlib.sha256(CHUNK1_TEXT.encode()).hexdigest()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO materials (id, project_id, original_name, sha256,"
            " status, pdf_pages, usable_pages, corpus_revision, warnings_json,"
            " error_code, file_path, file_size, job_id, created_at, updated_at)"
            " VALUES ('mat_direct', ?, 'x.pdf', ?, 'ready', 1, 1, 1, '[]', NULL,"
            " 'x.pdf', 100, NULL, '2026-09-19T00:00:00+00:00', '2026-09-19T00:00:00+00:00')",
            (project_id, "a" * 64),
        )
        conn.execute(
            "INSERT OR IGNORE INTO chunks (chunk_id, project_id, document_id,"
            " corpus_revision, pdf_page, page_start, page_end, text, text_sha256,"
            " extractor_version, tokenizer_version)"
            " VALUES ('chk_direct', ?, 'mat_direct', 1, 1, 0, ?, ?, ?,"
            " 'pypdf-5.9.0-nfc-v1', 'jieba-0.42.1+ascii-v1')",
            (project_id, len(CHUNK1_TEXT), CHUNK1_TEXT, sha1),
        )
        conn.execute(
            "UPDATE projects SET corpus_revision = 1 WHERE id = ?", (project_id,)
        )


def poll_job(client, job_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/v1/jobs/{job_id}")
        assert r.status_code == 200
        job = r.json()
        if job["status"] in {"succeeded", "failed", "cancelled", "blocked", "interrupted"}:
            return job
        time.sleep(0.05)
    pytest.fail(f"job {job_id} not terminal in time")


def poll_plan_id(client, job_id, timeout=10.0):
    job = poll_job(client, job_id)
    assert job["status"] == "succeeded", job
    return job["result_ref"]["id"]


class TestCommitRoute:
    """教师应用候选：201 DeckVersion、拒绝门、幂等重放（生成与应用分离收口）。"""

    def _ready_change(self, tmp_path, name):
        """建项目→种语料→种确认计划→直接跑生成（无 worker）→返回 (client, conn, pid, change_id)。"""
        from courseware_core.models import Job
        from courseware_core.services.generate_service import GenerateService

        db = tmp_path / name
        client = app_client(db)
        conn = connect(db)
        ctx = client.__enter__()
        pid = seed_ready_project(ctx, conn)
        seed_plan_row(conn, pid)
        r = ctx.post(
            f"/api/v1/projects/{pid}/generations", json=GEN_BODY,
            headers={"Idempotency-Key": "k-cr-g"},
        )
        assert r.status_code == 202
        job_id = r.json()["job_id"]
        with conn:
            conn.execute(
                "UPDATE projects SET active_job_id=NULL WHERE id=?", (pid,)
            )
            conn.execute(
                "UPDATE jobs SET status='running', worker_id='t' WHERE id=?", (job_id,)
            )
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        job = Job(**{k: row[k] for k in row.keys() if k in Job.model_fields})
        provider = StageProvider(plan_proposal())
        provider.queue("generate_content", [content_proposal()])
        provider.queue("verify_claims", [verdicts_supported()])
        ref = GenerateService(conn, provider=provider).handle_generate(job)
        return client, conn, pid, ref.id

    COMMIT_BODY = {"base_version": 0, "corpus_revision": 1, "acknowledged": True}

    def test_commit_201_deck_version(self, tmp_path):
        client, conn, pid, change_id = self._ready_change(tmp_path, "h.db")
        try:
            r = client.post(
                f"/api/v1/projects/{pid}/changes/{change_id}/commit",
                json=self.COMMIT_BODY, headers={"Idempotency-Key": "k-commit-1"},
            )
            assert r.status_code == 201
            body = r.json()
            assert body["version"] == 1 and body["project_id"] == pid
            proj = conn.execute(
                "SELECT current_version FROM projects WHERE id=?", (pid,)
            ).fetchone()
            assert proj["current_version"] == 1
            r2 = client.get(f"/api/v1/projects/{pid}/changes/{change_id}")
            assert r2.json()["status"] == "committed"
        finally:
            client.__exit__(None, None, None)
            conn.close()

    def test_commit_replay_same_key_same_result(self, tmp_path):
        client, conn, pid, change_id = self._ready_change(tmp_path, "i.db")
        try:
            headers = {"Idempotency-Key": "k-commit-2"}
            r1 = client.post(
                f"/api/v1/projects/{pid}/changes/{change_id}/commit",
                json=self.COMMIT_BODY, headers=headers,
            )
            r2 = client.post(
                f"/api/v1/projects/{pid}/changes/{change_id}/commit",
                json=self.COMMIT_BODY, headers=headers,
            )
            assert r1.status_code == r2.status_code == 201
            assert r1.json() == r2.json()
            n = conn.execute("SELECT COUNT(*) c FROM deck_versions").fetchone()["c"]
            assert n == 1
        finally:
            client.__exit__(None, None, None)
            conn.close()

    def test_double_commit_different_key_rejected(self, tmp_path):
        client, conn, pid, change_id = self._ready_change(tmp_path, "j.db")
        try:
            r1 = client.post(
                f"/api/v1/projects/{pid}/changes/{change_id}/commit",
                json=self.COMMIT_BODY, headers={"Idempotency-Key": "k-commit-3"},
            )
            assert r1.status_code == 201
            r2 = client.post(
                f"/api/v1/projects/{pid}/changes/{change_id}/commit",
                json=self.COMMIT_BODY, headers={"Idempotency-Key": "k-commit-4"},
            )
            assert r2.status_code == 409
            assert r2.json()["error"]["code"] == "CHANGE_NOT_COMMITTABLE"
        finally:
            client.__exit__(None, None, None)
            conn.close()

    def test_unacknowledged_422(self, tmp_path):
        client, conn, pid, change_id = self._ready_change(tmp_path, "k.db")
        try:
            r = client.post(
                f"/api/v1/projects/{pid}/changes/{change_id}/commit",
                json={"base_version": 0, "corpus_revision": 1, "acknowledged": False},
                headers={"Idempotency-Key": "k-commit-5"},
            )
            assert r.status_code == 422
        finally:
            client.__exit__(None, None, None)
            conn.close()

    def test_blocked_candidate_409(self, tmp_path):
        from courseware_core.models import Job
        from courseware_core.services.generate_service import GenerateService

        db = tmp_path / "l.db"
        client = app_client(db)
        conn = connect(db)
        with client:
            pid = seed_ready_project(client, conn)
            seed_plan_row(conn, pid)
            r = client.post(
                f"/api/v1/projects/{pid}/generations", json=GEN_BODY,
                headers={"Idempotency-Key": "k-bl"},
            )
            job_id = r.json()["job_id"]
            with conn:
                conn.execute("UPDATE projects SET active_job_id=NULL WHERE id=?", (pid,))
                conn.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            job = Job(**{k: row[k] for k in row.keys() if k in Job.model_fields})
            provider = StageProvider(plan_proposal())
            provider.queue("generate_content", [content_proposal()])
            bad = SemanticVerdicts.model_validate(
                {"checks": [{"claim_id": "clm1", "status": "conflict",
                             "reason": "材料互斥。"}], "unbound_assertions": []}
            )
            provider.queue("verify_claims", [bad])
            ref = GenerateService(conn, provider=provider).handle_generate(job)
            r = client.post(
                f"/api/v1/projects/{pid}/changes/{ref.id}/commit",
                json=self.COMMIT_BODY, headers={"Idempotency-Key": "k-commit-6"},
            )
            assert r.status_code == 409
            assert r.json()["error"]["code"] == "CHANGE_NOT_COMMITTABLE"
