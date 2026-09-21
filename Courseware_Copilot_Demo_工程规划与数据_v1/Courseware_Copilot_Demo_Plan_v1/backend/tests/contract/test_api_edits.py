"""T12 loop③：POST /projects/{id}/edits 契约测试（先红后绿）。"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from courseware_core.models import DeckSpec
from courseware_core.storage.database import connect
from courseware_core.storage.version_repository import VersionRepository

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
        "goals": ["理解 NVIC"],
        "target_slides": 8,
    },
    "consent_to_cloud_processing": True,
}


def deck_payload() -> DeckSpec:
    return DeckSpec(
        schema_version="1.0.0",
        project_id="unused",
        version=1,
        corpus_revision=1,
        course=PROJECT_BODY["course"],
        claims=[
            {
                "id": "clm_c1",
                "text": "NVIC 分组决定抢占与子优先级位数。",
                "kind": "direct",
                "evidence_refs": [
                    {"chunk_id": "chk_1", "document_id": "doc_1", "pdf_page": 1,
                     "start": 0, "end": 10, "quote": "分组决定…"}
                ],
            }
        ],
        slides=[
            {
                "id": f"s{i}",
                "title": f"页{i}",
                "layout": "concept",
                "blocks": [{"type": "teaching", "text": f"内容{i}"}],
            }
            for i in (1, 2, 3)
        ],
    )


@pytest.fixture()
def client_db(tmp_path):
    from courseware_api.main import create_app

    db_path = tmp_path / "data" / "app.db"
    app = create_app(db_path)
    conn = connect(db_path)
    with TestClient(app) as c:
        yield c, conn
    conn.close()


def seed_project_with_deck(client, conn):
    r = client.post(
        "/api/v1/projects", json=PROJECT_BODY, headers={"Idempotency-Key": "k-seed-e"}
    )
    assert r.status_code == 201
    project_id = r.json()["id"]
    with conn:
        conn.execute(
            "UPDATE projects SET corpus_revision = 1 WHERE id = ?", (project_id,)
        )
    VersionRepository(conn).commit_version(
        project_id, deck_payload(), expected_base_version=0, expected_corpus_revision=1
    )
    return project_id


def edit_body(instruction="把第二页精简成三点", targets=None, base=1, corpus=1):
    return {
        "instruction": instruction,
        "target_slide_ids": targets if targets is not None else ["s2"],
        "base_version": base,
        "corpus_revision": corpus,
    }


class TestEditsRoute:
    def test_free_text_edit_returns_202_and_edit_job(self, client_db):
        client, conn = client_db
        project_id = seed_project_with_deck(client, conn)
        r = client.post(
            f"/api/v1/projects/{project_id}/edits",
            json=edit_body(),
            headers={"Idempotency-Key": "k-e1"},
        )
        assert r.status_code == 202
        body = r.json()
        import jsonschema as js
        js.validate(body, sub_schema("JobAccepted"))
        job = client.get(f"/api/v1/jobs/{body['job_id']}")
        assert job.status_code == 200
        assert job.json()["kind"] == "edit"
        assert job.json()["status"] == "queued"
        assert job.json()["base_version"] == 1

    def test_structured_reorder_returns_202(self, client_db):
        client, conn = client_db
        project_id = seed_project_with_deck(client, conn)
        r = client.post(
            f"/api/v1/projects/{project_id}/edits",
            json=edit_body(
                '{"action": "reorder", "slide_ids": ["s3", "s1", "s2"]}',
                targets=["s1", "s2", "s3"],
            ),
            headers={"Idempotency-Key": "k-e2"},
        )
        assert r.status_code == 202

    def test_unknown_target_slide_422_edit_unsupported(self, client_db):
        client, conn = client_db
        project_id = seed_project_with_deck(client, conn)
        r = client.post(
            f"/api/v1/projects/{project_id}/edits",
            json=edit_body(targets=["s9"]),
            headers={"Idempotency-Key": "k-e3"},
        )
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "EDIT_UNSUPPORTED"

    def test_structured_unknown_action_422_edit_unsupported(self, client_db):
        client, conn = client_db
        project_id = seed_project_with_deck(client, conn)
        r = client.post(
            f"/api/v1/projects/{project_id}/edits",
            json=edit_body(
                '{"action": "delete_slide", "slide_ids": ["s1"]}', targets=["s1"]
            ),
            headers={"Idempotency-Key": "k-e4"},
        )
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "EDIT_UNSUPPORTED"

    def test_structured_partial_permutation_422(self, client_db):
        client, conn = client_db
        project_id = seed_project_with_deck(client, conn)
        r = client.post(
            f"/api/v1/projects/{project_id}/edits",
            json=edit_body(
                '{"action": "reorder", "slide_ids": ["s3", "s1"]}',
                targets=["s1", "s2", "s3"],
            ),
            headers={"Idempotency-Key": "k-e5"},
        )
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "EDIT_UNSUPPORTED"

    def test_stale_base_409_version_conflict(self, client_db):
        client, conn = client_db
        project_id = seed_project_with_deck(client, conn)
        r = client.post(
            f"/api/v1/projects/{project_id}/edits",
            json=edit_body(base=2),
            headers={"Idempotency-Key": "k-e6"},
        )
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "VERSION_CONFLICT"

    def test_corpus_mismatch_409(self, client_db):
        client, conn = client_db
        project_id = seed_project_with_deck(client, conn)
        r = client.post(
            f"/api/v1/projects/{project_id}/edits",
            json=edit_body(corpus=7),
            headers={"Idempotency-Key": "k-e7"},
        )
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "CORPUS_CHANGED"

    def test_active_job_409_project_busy(self, client_db):
        client, conn = client_db
        project_id = seed_project_with_deck(client, conn)
        first = client.post(
            f"/api/v1/projects/{project_id}/edits",
            json=edit_body(),
            headers={"Idempotency-Key": "k-e8a"},
        )
        assert first.status_code == 202
        second = client.post(
            f"/api/v1/projects/{project_id}/edits",
            json=edit_body(targets=["s1"]),
            headers={"Idempotency-Key": "k-e8b"},
        )
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "PROJECT_BUSY"

    def test_unknown_project_404(self, client_db):
        client, conn = client_db
        r = client.post(
            "/api/v1/projects/prj_missing/edits",
            json=edit_body(),
            headers={"Idempotency-Key": "k-e9"},
        )
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "PROJECT_NOT_FOUND"

    def test_missing_idempotency_key_422(self, client_db):
        client, conn = client_db
        project_id = seed_project_with_deck(client, conn)
        r = client.post(f"/api/v1/projects/{project_id}/edits", json=edit_body())
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_idempotent_replay_returns_same_job(self, client_db):
        client, conn = client_db
        project_id = seed_project_with_deck(client, conn)
        headers = {"Idempotency-Key": "k-e10"}
        first = client.post(
            f"/api/v1/projects/{project_id}/edits", json=edit_body(), headers=headers
        )
        second = client.post(
            f"/api/v1/projects/{project_id}/edits", json=edit_body(), headers=headers
        )
        assert first.status_code == 202
        assert second.json() == first.json()
        rows = conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE project_id = ?", (project_id,)
        ).fetchone()
        assert rows["n"] == 1
