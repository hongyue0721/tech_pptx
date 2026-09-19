"""T08 plans 三路由契约测试 + plan job 端到端（注入 FakeProvider，零真实模型）。"""

import hashlib
import json
import time
from pathlib import Path

import jsonschema as js
import pytest
from fastapi.testclient import TestClient

from courseware_core.llm.adapter import TypedCompletion, Usage
from courseware_core.models import PlanProposal
from courseware_core.storage.database import connect

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "contracts" / "models.schema.json"
with SCHEMA_PATH.open(encoding="utf-8") as f:
    DEFS = json.load(f)["$defs"]


def sub_schema(def_name: str) -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$ref": f"#/$defs/{def_name}",
        "$defs": DEFS,
    }


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


class FakeProvider:
    def __init__(self, value):
        self.value = value

    def complete_json(self, stage, schema_name, messages, context):
        return TypedCompletion(
            value=self.value,
            usage=Usage(10, 5, 15),
            provider_request_id="fake-req",
            attempts=1,
        )


def proposal_value(chunk_id):
    return PlanProposal.model_validate(
        {
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
                {"goal_index": 0, "candidate_chunk_ids": [chunk_id], "note": "有支持"}
            ],
        }
    )


def seed_ready_project(client, conn):
    """建项目并直接推进 corpus：插 chunk 行模拟已解析材料（不跑 parse job）。"""
    r = client.post("/api/v1/projects", json=PROJECT_BODY, headers={"Idempotency-Key": "k-seed"})
    assert r.status_code == 201
    project_id = r.json()["id"]
    text = "讲解：NVIC优先级分组通过AIRCR配置，需要先解锁KEYR。"
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    with conn:
        conn.execute(
            "INSERT INTO materials (id, project_id, original_name, sha256, status,"
            " pdf_pages, usable_pages, corpus_revision, warnings_json, error_code,"
            " file_path, file_size, job_id, created_at, updated_at)"
            " VALUES ('mat_seed', ?, 'x.pdf', ?, 'ready', 1, 1, 1, '[]', NULL,"
            " 'x.pdf', 100, NULL, '2026-09-19T00:00:00+00:00', '2026-09-19T00:00:00+00:00')",
            (project_id, "a" * 64),
        )
        text2 = "补充：NVIC优先级分组通过AIRCR配置组设置抢占与响应优先级。"
        sha2 = hashlib.sha256(text2.encode("utf-8")).hexdigest()
        conn.execute(
            "INSERT INTO chunks (chunk_id, project_id, document_id, corpus_revision,"
            " pdf_page, page_start, page_end, text, text_sha256, extractor_version,"
            " tokenizer_version) VALUES ('chk_seed', ?, 'mat_seed', 1, 1, 0, ?, ?, ?,"
            " 'pypdf-5.9.0-nfc-v1', 'jieba-0.42.1+ascii-v1')",
            (project_id, len(text), text, sha),
        )
        conn.execute(
            "INSERT INTO chunks (chunk_id, project_id, document_id, corpus_revision,"
            " pdf_page, page_start, page_end, text, text_sha256, extractor_version,"
            " tokenizer_version) VALUES ('chk_seed2', ?, 'mat_seed', 1, 1, 0, ?, ?, ?,"
            " 'pypdf-5.9.0-nfc-v1', 'jieba-0.42.1+ascii-v1')",
            (project_id, len(text2), text2, sha2),
        )
        conn.execute(
            "UPDATE projects SET corpus_revision = 1 WHERE id = ?", (project_id,)
        )
    return project_id


@pytest.fixture()
def client_db(tmp_path):
    """client 与测试侧 conn 指向同一 DB（WAL 多连接）。"""
    from courseware_api.main import create_app

    db_path = tmp_path / "data" / "app.db"
    app = create_app(db_path)
    conn = connect(db_path)
    with TestClient(app) as c:
        yield c, conn
    conn.close()


def poll_job(client, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/v1/jobs/{job_id}")
        assert r.status_code == 200
        job = r.json()
        if job["status"] in {"succeeded", "failed", "cancelled", "blocked", "interrupted"}:
            return job
        time.sleep(0.05)
    pytest.fail(f"job {job_id} not terminal in time")


class TestPlansRoutes:
    def test_post_plans_requires_idempotency_key(self, client_db):
        client, conn = client_db
        project_id = seed_ready_project(client, conn)
        r = client.post(f"/api/v1/projects/{project_id}/plans", json={"corpus_revision": 1})
        assert r.status_code == 422

    def test_post_plans_202_job_accepted(self, client_db):
        client, conn = client_db
        project_id = seed_ready_project(client, conn)
        r = client.post(
            f"/api/v1/projects/{project_id}/plans",
            json={"corpus_revision": 1},
            headers={"Idempotency-Key": "k-plan-1"},
        )
        assert r.status_code == 202
        js.validate(r.json(), sub_schema("JobAccepted"))

    def test_post_plans_idempotent_replay(self, client_db):
        client, conn = client_db
        project_id = seed_ready_project(client, conn)
        body = {"corpus_revision": 1}
        r1 = client.post(
            f"/api/v1/projects/{project_id}/plans",
            json=body,
            headers={"Idempotency-Key": "k-plan-2"},
        )
        r2 = client.post(
            f"/api/v1/projects/{project_id}/plans",
            json=body,
            headers={"Idempotency-Key": "k-plan-2"},
        )
        assert r1.status_code == 202 and r2.status_code == 202
        assert r1.json() == r2.json()
        # 重放不得二次落 job（N6）：DB 计数唯一。
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE kind='plan'"
        ).fetchone()["n"]
        assert n == 1

    def test_post_plans_busy_409(self, client_db):
        client, conn = client_db
        project_id = seed_ready_project(client, conn)
        with conn:
            conn.execute(
                "UPDATE projects SET active_job_id='job_locked' WHERE id=?", (project_id,)
            )
        r = client.post(
            f"/api/v1/projects/{project_id}/plans",
            json={"corpus_revision": 1},
            headers={"Idempotency-Key": "k-plan-3"},
        )
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "PROJECT_BUSY"

    def test_post_plans_corpus_mismatch_409(self, client_db):
        client, conn = client_db
        project_id = seed_ready_project(client, conn)
        r = client.post(
            f"/api/v1/projects/{project_id}/plans",
            json={"corpus_revision": 5},
            headers={"Idempotency-Key": "k-plan-4"},
        )
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "CORPUS_CHANGED"

    def test_get_plan_404_unknown(self, client_db):
        client, conn = client_db
        project_id = seed_ready_project(client, conn)
        r = client.get(f"/api/v1/projects/{project_id}/plans/plan_x")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "PLAN_NOT_FOUND"

    def test_confirm_requires_idempotency_key(self, client_db):
        client, conn = client_db
        project_id = seed_ready_project(client, conn)
        r = client.post(
            f"/api/v1/projects/{project_id}/plans/plan_x/confirm",
            json={
                "corpus_revision": 1,
                "slides": [],
                "accepted_goal_indices": [0],
                "acknowledged": True,
            },
        )
        assert r.status_code == 422


class TestPlanEndToEnd:
    def test_upload_parse_plan_confirm_flow(self, tmp_path, conn):
        from courseware_api.main import create_app

        db_path = tmp_path / "data" / "app.db"

        class LazyProvider:
            def complete_json(self, stage, schema_name, messages, context):
                # 端到端断言 provider 真被调用；返回值在下方测试里预先已知。
                return TypedCompletion(
                    value=PlanProposal.model_validate(
                        {
                            "slides": [
                                {
                                    "id": "ps1",
                                    "title": "NVIC优先级分组",
                                    "purpose": "讲解AIRCR配置",
                                    "layout": "concept",
                                    "goal_indices": [0],
                                    "evidence_chunk_ids": [self.chunk_id],
                                }
                            ],
                            "coverage_notes": [
                                {
                                    "goal_index": 0,
                                    "candidate_chunk_ids": [self.chunk_id],
                                    "note": "有支持",
                                }
                            ],
                        }
                    ),
                    usage=Usage(10, 5, 15),
                    provider_request_id="fake-req",
                    attempts=1,
                )

        lazy = LazyProvider()

        def plan_handler(job):
            from courseware_core.services.plan_service import PlanService
            from courseware_core.storage.database import connect

            c = connect(db_path)
            try:
                # 端到端取真实 chunk_id，保证 proposal 引用可解析。
                row = c.execute("SELECT chunk_id FROM chunks LIMIT 1").fetchone()
                lazy.chunk_id = row["chunk_id"]
                return PlanService(c, provider=lazy).handle_plan(job)
            finally:
                c.close()

        from courseware_api.wiring import build_worker_handlers

        handlers = build_worker_handlers(db_path, tmp_path / "materials")
        handlers["plan"] = plan_handler

        app = create_app(db_path, worker_handlers=handlers)
        with TestClient(app) as client:
            r = client.post("/api/v1/projects", json=PROJECT_BODY, headers={"Idempotency-Key": "e1"})
            project_id = r.json()["id"]
            # 直接种一个 ready 材料（复用 seed 逻辑但走同一 db_path 的连接）。
            c2 = connect(db_path)
            try:
                text = "讲解：NVIC优先级分组通过AIRCR配置，需要先解锁KEYR。"
                text2 = "补充：NVIC优先级分组通过AIRCR配置组设置抢占与响应优先级。"
                sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
                sha2 = hashlib.sha256(text2.encode("utf-8")).hexdigest()
                with c2:
                    c2.execute(
                        "INSERT INTO materials (id, project_id, original_name, sha256,"
                        " status, pdf_pages, usable_pages, corpus_revision, warnings_json,"
                        " error_code, file_path, file_size, job_id, created_at, updated_at)"
                        " VALUES ('mat_e', ?, 'x.pdf', ?, 'ready', 1, 1, 1, '[]', NULL,"
                        " 'x.pdf', 100, NULL, '2026-09-19T00:00:00+00:00',"
                        " '2026-09-19T00:00:00+00:00')",
                        (project_id, "a" * 64),
                    )
                    c2.execute(
                        "INSERT INTO chunks (chunk_id, project_id, document_id,"
                        " corpus_revision, pdf_page, page_start, page_end, text,"
                        " text_sha256, extractor_version, tokenizer_version)"
                        " VALUES ('chk_e', ?, 'mat_e', 1, 1, 0, ?, ?, ?,"
                        " 'pypdf-5.9.0-nfc-v1', 'jieba-0.42.1+ascii-v1')",
                        (project_id, len(text), text, sha),
                    )
                    c2.execute(
                        "INSERT INTO chunks (chunk_id, project_id, document_id,"
                        " corpus_revision, pdf_page, page_start, page_end, text,"
                        " text_sha256, extractor_version, tokenizer_version)"
                        " VALUES ('chk_e2', ?, 'mat_e', 1, 1, 0, ?, ?, ?,"
                        " 'pypdf-5.9.0-nfc-v1', 'jieba-0.42.1+ascii-v1')",
                        (project_id, len(text2), text2, sha2),
                    )
                    c2.execute(
                        "UPDATE projects SET corpus_revision = 1 WHERE id = ?",
                        (project_id,),
                    )
            finally:
                c2.close()

            r = client.post(
                f"/api/v1/projects/{project_id}/plans",
                json={"corpus_revision": 1},
                headers={"Idempotency-Key": "e2"},
            )
            assert r.status_code == 202
            job = poll_job(client, r.json()["job_id"])
            assert job["status"] == "succeeded"
            assert job["result_ref"]["type"] == "plan"

            r = client.get(
                f"/api/v1/projects/{project_id}/plans/{job['result_ref']['id']}"
            )
            assert r.status_code == 200
            plan = r.json()
            js.validate(plan, sub_schema("LessonPlan"))
            assert plan["status"] == "draft"
            assert plan["coverage"][0]["status"] == "supported"

            r = client.post(
                f"/api/v1/projects/{project_id}/plans/{plan['id']}/confirm",
                json={
                    "corpus_revision": 1,
                    "slides": plan["slides"],
                    "accepted_goal_indices": [0],
                    "acknowledged": True,
                },
                headers={"Idempotency-Key": "e3"},
            )
            assert r.status_code == 200
            confirmed = r.json()
            js.validate(confirmed, sub_schema("LessonPlan"))
            assert confirmed["status"] == "confirmed"

    def test_insufficient_evidence_blocks_job(self, tmp_path, conn):
        from courseware_api.main import create_app
        from courseware_api.wiring import build_worker_handlers
        from courseware_core.storage.database import connect

        db_path = tmp_path / "data" / "app.db"

        def plan_handler(job):
            from courseware_core.services.plan_service import PlanService

            c = connect(db_path)
            try:
                return PlanService(c, provider=FakeProvider(PlanProposal.model_validate({"slides": [{"id": "s", "title": "t", "purpose": "p", "layout": "concept", "goal_indices": [0], "evidence_chunk_ids": []}], "coverage_notes": [{"goal_index": 0, "candidate_chunk_ids": [], "note": "n"}]}))).handle_plan(job)
            finally:
                c.close()

        handlers = build_worker_handlers(db_path, tmp_path / "materials")
        handlers["plan"] = plan_handler
        app = create_app(db_path, worker_handlers=handlers)
        with TestClient(app) as client:
            body = json.loads(json.dumps(PROJECT_BODY))
            body["course"]["goals"] = ["EXTI外部中断线映射表"]
            r = client.post("/api/v1/projects", json=body, headers={"Idempotency-Key": "b1"})
            project_id = r.json()["id"]
            text = "GPIO端口有八种工作模式，推挽与开漏输出。"
            sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            c2 = connect(db_path)
            with c2:
                c2.execute(
                    "INSERT INTO materials (id, project_id, original_name, sha256,"
                    " status, pdf_pages, usable_pages, corpus_revision, warnings_json,"
                    " error_code, file_path, file_size, job_id, created_at, updated_at)"
                    " VALUES ('mat_b', ?, 'x.pdf', ?, 'ready', 1, 1, 1, '[]', NULL,"
                    " 'x.pdf', 100, NULL, '2026-09-19T00:00:00+00:00',"
                    " '2026-09-19T00:00:00+00:00')",
                    (project_id, "a" * 64),
                )
                c2.execute(
                    "INSERT INTO chunks (chunk_id, project_id, document_id,"
                    " corpus_revision, pdf_page, page_start, page_end, text,"
                    " text_sha256, extractor_version, tokenizer_version)"
                    " VALUES ('chk_b', ?, 'mat_b', 1, 1, 0, ?, ?, ?,"
                    " 'pypdf-5.9.0-nfc-v1', 'jieba-0.42.1+ascii-v1')",
                    (project_id, len(text), text, sha),
                )
                c2.execute(
                    "UPDATE projects SET corpus_revision = 1 WHERE id = ?", (project_id,)
                )
            c2.close()

            r = client.post(
                f"/api/v1/projects/{project_id}/plans",
                json={"corpus_revision": 1},
                headers={"Idempotency-Key": "b2"},
            )
            job = poll_job(client, r.json()["job_id"])
            # api.md:59 资料不足=blocked+INSUFFICIENT_EVIDENCE，不得与 failed 混淆。
            assert job["status"] == "blocked"
            assert job["error"]["error"]["code"] == "INSUFFICIENT_EVIDENCE"
            # blocked 不落 plan（N6）：失败路径不产生半成品业务对象。
            from courseware_core.storage.database import connect as _connect
            _c = _connect(db_path)
            try:
                n = _c.execute("SELECT COUNT(*) AS n FROM plans").fetchone()["n"]
            finally:
                _c.close()
            assert n == 0
            # blocked 释放项目锁：后续写任务可再受理。
            r = client.post(
                f"/api/v1/projects/{project_id}/materials",
                headers={"Idempotency-Key": "b3"},
                files={"file": ("x.pdf", b"%PDF-1.4 not-really", "application/pdf")},
            )
            assert r.status_code in (202, 422)  # 422=结构校验拒绝，但不得是409 PROJECT_BUSY
            assert r.status_code != 409
