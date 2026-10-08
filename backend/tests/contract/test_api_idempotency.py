import json
from pathlib import Path

import jsonschema as js
import pytest
from fastapi.testclient import TestClient

from courseware_api.main import create_app

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "contracts" / "models.schema.json"
with SCHEMA_PATH.open(encoding="utf-8") as f:
    DEFS = json.load(f)["$defs"]


def sub_schema(def_name: str) -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$ref": f"#/$defs/{def_name}",
        "$defs": DEFS,
    }


def project_body(topic: str = "STM32 中断") -> dict:
    return {
        "course": {
            "topic": topic,
            "audience": "大二",
            "duration_minutes": 45,
            "goals": ["理解 NVIC"],
            "target_slides": 8,
        },
        "consent_to_cloud_processing": True,
    }


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path / "data" / "app.db")
    with TestClient(app) as c:
        yield c


def project_count(client: TestClient) -> int:
    import sqlite3

    conn = sqlite3.connect(client.app.state.db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    finally:
        conn.close()


def test_same_key_same_body_replays_same_project(client):
    first = client.post(
        "/api/v1/projects", json=project_body(), headers={"Idempotency-Key": "k1"}
    )
    second = client.post(
        "/api/v1/projects", json=project_body(), headers={"Idempotency-Key": "k1"}
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    assert project_count(client) == 1


def test_same_key_different_body_conflicts(client):
    ok = client.post(
        "/api/v1/projects", json=project_body("A"), headers={"Idempotency-Key": "k1"}
    )
    assert ok.status_code == 201
    conflict = client.post(
        "/api/v1/projects", json=project_body("B"), headers={"Idempotency-Key": "k1"}
    )
    assert conflict.status_code == 409
    body = conflict.json()
    js.validate(body, sub_schema("ErrorResponse"))
    assert body["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert project_count(client) == 1


def test_different_keys_create_distinct_projects(client):
    a = client.post(
        "/api/v1/projects", json=project_body("A"), headers={"Idempotency-Key": "k1"}
    )
    b = client.post(
        "/api/v1/projects", json=project_body("A"), headers={"Idempotency-Key": "k2"}
    )
    assert a.json()["id"] != b.json()["id"]
    assert project_count(client) == 2


def test_same_key_different_project_scopes_are_independent(client):
    created = client.post(
        "/api/v1/projects", json=project_body(), headers={"Idempotency-Key": "k-seed"}
    )
    pid = created.json()["id"]
    d1 = client.request(
        "DELETE",
        f"/api/v1/projects/{pid}",
        json={"acknowledged": True},
        headers={"Idempotency-Key": "same-del-key"},
    )
    assert d1.status_code == 204
    d2 = client.request(
        "DELETE",
        "/api/v1/projects/nonexistent",
        json={"acknowledged": True},
        headers={"Idempotency-Key": "same-del-key"},
    )
    assert d2.status_code == 404
    assert d2.json()["error"]["code"] == "PROJECT_NOT_FOUND"


def test_delete_replay_returns_same_status(client):
    created = client.post(
        "/api/v1/projects", json=project_body(), headers={"Idempotency-Key": "k-seed"}
    )
    pid = created.json()["id"]
    first = client.request(
        "DELETE",
        f"/api/v1/projects/{pid}",
        json={"acknowledged": True},
        headers={"Idempotency-Key": "dk1"},
    )
    second = client.request(
        "DELETE",
        f"/api/v1/projects/{pid}",
        json={"acknowledged": True},
        headers={"Idempotency-Key": "dk1"},
    )
    assert first.status_code == second.status_code == 204
    assert client.get(f"/api/v1/projects/{pid}").status_code == 404
