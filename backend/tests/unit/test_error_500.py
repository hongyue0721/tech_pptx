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


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path / "data" / "app.db")

    @app.get("/api/v1/_boom")
    def _boom():
        raise RuntimeError("injected failure")

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_unhandled_exception_returns_typed_500_shape(client):
    r = client.get("/api/v1/_boom")
    assert r.status_code == 500
    body = r.json()
    js.validate(body, sub_schema("ErrorResponse"))
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert body["error"]["request_id"]


def test_500_response_carries_request_id_header(client):
    r = client.get("/api/v1/_boom", headers={"X-Request-ID": "req_inject_1"})
    assert r.headers.get("X-Request-ID") == "req_inject_1"
    assert r.json()["error"]["request_id"] == "req_inject_1"
