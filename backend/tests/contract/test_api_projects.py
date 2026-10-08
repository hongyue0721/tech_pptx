import json
import tempfile
from pathlib import Path

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


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path / "data" / "app.db")
    with TestClient(app) as c:
        yield c


def valid_project_body() -> dict:
    return {
        "course": {
            "topic": "STM32 中断机制",
            "audience": "大二学生",
            "duration_minutes": 45,
            "goals": ["理解 NVIC 分组"],
            "target_slides": 8,
        },
        "consent_to_cloud_processing": True,
    }


def test_health_matches_schema(client: TestClient):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    jsonschema_validate(r.json(), "Health")


def jsonschema_validate(instance: dict, def_name: str):
    import jsonschema as js

    js.validate(instance, sub_schema(def_name))


def test_create_project_returns_typed_201(client: TestClient):
    r = client.post(
        "/api/v1/projects",
        json=valid_project_body(),
        headers={"Idempotency-Key": "k1"},
    )
    assert r.status_code == 201
    body = r.json()
    jsonschema_validate(body, "Project")
    assert body["current_version"] == 0
    assert body["corpus_revision"] == 0
    assert body["active_job_id"] is None


def test_get_project_roundtrip(client: TestClient):
    created = client.post(
        "/api/v1/projects",
        json=valid_project_body(),
        headers={"Idempotency-Key": "k1"},
    ).json()
    r = client.get(f"/api/v1/projects/{created['id']}")
    assert r.status_code == 200
    assert r.json() == created


def test_get_missing_project_404_shape(client: TestClient):
    r = client.get("/api/v1/projects/nonexistent")
    assert r.status_code == 404
    body = r.json()
    jsonschema_validate(body, "ErrorResponse")
    assert body["error"]["code"] == "PROJECT_NOT_FOUND"
    assert body["error"]["request_id"] == r.headers["X-Request-ID"]


def test_create_without_idempotency_key_rejected(client: TestClient):
    r = client.post("/api/v1/projects", json=valid_project_body())
    assert r.status_code == 422
    body = r.json()
    jsonschema_validate(body, "ErrorResponse")
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_create_invalid_body_422_field_localized(client: TestClient):
    bad = valid_project_body()
    bad["course"]["duration_minutes"] = 5
    r = client.post(
        "/api/v1/projects", json=bad, headers={"Idempotency-Key": "k1"}
    )
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    fields = body["error"]["details"]["fields"]
    assert any("duration_minutes" in loc for f in fields for loc in f["location"])


def test_delete_flow(client: TestClient):
    created = client.post(
        "/api/v1/projects",
        json=valid_project_body(),
        headers={"Idempotency-Key": "k1"},
    ).json()
    r = client.request(
        "DELETE",
        f"/api/v1/projects/{created['id']}",
        json={"acknowledged": True},
        headers={"Idempotency-Key": "k2"},
    )
    assert r.status_code == 204
    assert client.get(f"/api/v1/projects/{created['id']}").status_code == 404


def test_delete_requires_acknowledged_true(client: TestClient):
    created = client.post(
        "/api/v1/projects",
        json=valid_project_body(),
        headers={"Idempotency-Key": "k1"},
    ).json()
    r = client.request(
        "DELETE",
        f"/api/v1/projects/{created['id']}",
        json={"acknowledged": False},
        headers={"Idempotency-Key": "k2"},
    )
    assert r.status_code == 422


def test_request_id_echo_and_generation(client: TestClient):
    r = client.get("/api/v1/health", headers={"X-Request-ID": "trace-abc"})
    assert r.headers["X-Request-ID"] == "trace-abc"
    r = client.get("/api/v1/health")
    assert r.headers["X-Request-ID"].startswith("req_")
    r = client.get("/api/v1/health", headers={"X-Request-ID": "x" * 200})
    assert r.headers["X-Request-ID"] != "x" * 200


def test_unregistered_route_404_uses_unified_error_shape(client: TestClient):
    r = client.get("/api/v1/nonexistent")
    assert r.status_code == 404
    body = r.json()
    jsonschema_validate(body, "ErrorResponse")
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["request_id"] == r.headers["X-Request-ID"]


def test_wrong_method_405_uses_unified_error_shape(client: TestClient):
    r = client.patch("/api/v1/health")
    assert r.status_code == 405
    body = r.json()
    jsonschema_validate(body, "ErrorResponse")
    assert body["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert body["error"]["request_id"] != ""
