import json
from pathlib import Path

import jsonschema as js
import pytest
from fastapi.testclient import TestClient

from courseware_api.main import create_app
from courseware_core.models import Job
from courseware_core.storage.database import connect
from courseware_core.storage.job_repository import JobRepository

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "contracts" / "models.schema.json"
with SCHEMA_PATH.open(encoding="utf-8") as f:
    DEFS = json.load(f)["$defs"]

T0 = "2026-09-19T00:00:00+00:00"


def sub_schema(def_name: str) -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$ref": f"#/$defs/{def_name}",
        "$defs": DEFS,
    }


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path / "data" / "app.db")
    with TestClient(app) as c:
        yield c


def seed_project(client: TestClient) -> str:
    r = client.post(
        "/api/v1/projects",
        json={
            "course": {
                "topic": "STM32 中断",
                "audience": "大二",
                "duration_minutes": 45,
                "goals": ["理解 NVIC"],
                "target_slides": 8,
            },
            "consent_to_cloud_processing": True,
        },
        headers={"Idempotency-Key": "seed-key"},
    )
    assert r.status_code == 201
    return r.json()["id"]


def seed_job(client: TestClient, project_id: str, job_id: str, status: str = "queued") -> Job:
    conn = connect(client.app.state.db_path)
    try:
        job = Job(
            id=job_id,
            project_id=project_id,
            kind="parse",
            status=status,
            stage="queued",
            cancel_requested=False,
            base_version=0,
            corpus_revision=1,
            created_at=T0,
            updated_at=T0,
        )
        JobRepository(conn).create(job, request_id="req_seed")
        return job
    finally:
        conn.close()


def test_get_job_missing_returns_typed_404(client):
    r = client.get("/api/v1/jobs/nope")
    assert r.status_code == 404
    body = r.json()
    js.validate(body, sub_schema("ErrorResponse"))
    assert body["error"]["code"] == "JOB_NOT_FOUND"


def test_get_job_returns_contract_job(client):
    pid = seed_project(client)
    seed_job(client, pid, "job_x")
    r = client.get("/api/v1/jobs/job_x")
    assert r.status_code == 200
    js.validate(r.json(), sub_schema("Job"))
    assert r.json()["id"] == "job_x"
    assert r.json()["status"] == "queued"


def test_cancel_requires_idempotency_key(client):
    pid = seed_project(client)
    seed_job(client, pid, "job_c1")
    r = client.post("/api/v1/jobs/job_c1/cancel")
    assert r.status_code == 422
    body = r.json()
    js.validate(body, sub_schema("ErrorResponse"))
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_cancel_queued_job_becomes_cancelled(client):
    pid = seed_project(client)
    seed_job(client, pid, "job_c2")
    r = client.post("/api/v1/jobs/job_c2/cancel", headers={"Idempotency-Key": "ck1"})
    assert r.status_code == 200
    js.validate(r.json(), sub_schema("Job"))
    assert r.json()["status"] == "cancelled"


def test_cancel_replay_same_key_returns_same_result(client):
    pid = seed_project(client)
    seed_job(client, pid, "job_c3")
    first = client.post("/api/v1/jobs/job_c3/cancel", headers={"Idempotency-Key": "ck1"})
    second = client.post("/api/v1/jobs/job_c3/cancel", headers={"Idempotency-Key": "ck1"})
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


def test_cancel_terminal_job_is_noop_idempotent(client):
    pid = seed_project(client)
    seed_job(client, pid, "job_c4", status="succeeded")
    r = client.post("/api/v1/jobs/job_c4/cancel", headers={"Idempotency-Key": "ck9"})
    assert r.status_code == 200
    assert r.json()["status"] == "succeeded"


def test_cancel_missing_job_returns_404(client):
    r = client.post("/api/v1/jobs/nope/cancel", headers={"Idempotency-Key": "ck1"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "JOB_NOT_FOUND"
