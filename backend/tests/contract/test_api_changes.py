"""T09 changes 读取路由契约测试（生成/提交在 test_api_generate.py）。"""

import json
from pathlib import Path

import jsonschema as js
import pytest
from fastapi.testclient import TestClient

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

CANDIDATE_ROW = {
    "id": "chg_x1",
    "project_id": None,  # seed 时填真实项目 id
    "base_version": 0,
    "corpus_revision": 1,
    "status": "ready",
    "kind": "generation",
    "affected_slide_ids": ["sld_001"],
    "summary": "候选",
    "candidate": {
        "schema_version": "1.0.0",
        "project_id": None,
        "version": 1,
        "corpus_revision": 1,
        "course": PROJECT_BODY["course"],
        "claims": [],
        "slides": [
            {
                "id": "sld_001",
                "title": "NVIC 分组",
                "layout": "concept",
                "blocks": [{"type": "teaching", "text": "先分组再设优先级。"}],
            }
        ],
    },
    "validation": {
        "schema_valid": True,
        "relations_valid": True,
        "layout_valid": True,
        "claim_checks": [],
        "warnings": [],
        "can_commit": True,
        "model_id": None,
        "prompt_version": "content-v1+verify-v1",
        "checked_at": "2026-09-20T12:00:00+00:00",
        "raw_result_sha256": None,
        "unbound_assertions": [],
    },
    "created_at": "2026-09-20T12:00:00+00:00",
}


@pytest.fixture()
def client_db(tmp_path):
    from courseware_api.main import create_app

    db_path = tmp_path / "data" / "app.db"
    app = create_app(db_path)
    conn = connect(db_path)
    with TestClient(app) as c:
        yield c, conn
    conn.close()


def seed_project(client, conn):
    r = client.post(
        "/api/v1/projects", json=PROJECT_BODY, headers={"Idempotency-Key": "k-seed-c"}
    )
    assert r.status_code == 201
    return r.json()["id"]


def insert_change(conn, project_id, status="ready"):
    row = dict(CANDIDATE_ROW)
    row["project_id"] = project_id
    row["candidate"] = dict(row["candidate"], project_id=project_id)
    with conn:
        conn.execute(
            "INSERT INTO changes (id, project_id, base_version, corpus_revision,"
            " status, kind, change_json, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["id"],
                project_id,
                row["base_version"],
                row["corpus_revision"],
                status,
                row["kind"],
                json.dumps(row, ensure_ascii=False),
                row["created_at"],
                row["created_at"],
            ),
        )
    return row


class TestGetChange:
    def test_get_change_unknown_404_typed(self, client_db):
        client, conn = client_db
        project_id = seed_project(client, conn)
        r = client.get(f"/api/v1/projects/{project_id}/changes/chg_missing")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "CHANGE_NOT_FOUND"

    def test_get_change_returns_contract_shape(self, client_db):
        client, conn = client_db
        project_id = seed_project(client, conn)
        insert_change(conn, project_id)
        r = client.get(f"/api/v1/projects/{project_id}/changes/chg_x1")
        assert r.status_code == 200
        js.validate(r.json(), sub_schema("CandidateChange"))

    def test_get_change_cross_project_404(self, client_db):
        # 候选属项目作用域：拿 A 项目的 id 查 B 项目必须 404，不泄露存在性。
        client, conn = client_db
        owner = seed_project(client, conn)
        other_body = dict(PROJECT_BODY)
        r = client.post(
            "/api/v1/projects", json=other_body, headers={"Idempotency-Key": "k-seed-c2"}
        )
        other = r.json()["id"]
        insert_change(conn, owner)
        resp = client.get(f"/api/v1/projects/{other}/changes/chg_x1")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "CHANGE_NOT_FOUND"
