"""T12 loop②：POST /projects/{id}/restores 契约测试（先红后绿）。"""

import json
from pathlib import Path

import jsonschema as js
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


def deck_payload(version: int, text: str, corpus_revision: int = 1) -> DeckSpec:
    return DeckSpec(
        schema_version="1.0.0",
        project_id="unused",
        version=version,
        corpus_revision=corpus_revision,
        course=PROJECT_BODY["course"],
        claims=[],
        slides=[
            {
                "id": "sld_001",
                "title": f"页 {text}",
                "layout": "title",
                "blocks": [{"type": "teaching", "text": text}],
            }
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


def seed_project_with_two_versions(client, conn):
    r = client.post(
        "/api/v1/projects", json=PROJECT_BODY, headers={"Idempotency-Key": "k-seed-r"}
    )
    assert r.status_code == 201
    project_id = r.json()["id"]
    # 新建项目 corpus_revision=0，材料入库才推进到 1（docs/04）；restore 契约要求 >=1，模拟已入库。
    with conn:
        conn.execute(
            "UPDATE projects SET corpus_revision = 1 WHERE id = ?", (project_id,)
        )
    versions = VersionRepository(conn)
    versions.commit_version(
        project_id, deck_payload(1, "one"), expected_base_version=0,
        expected_corpus_revision=1,
    )
    versions.commit_version(
        project_id, deck_payload(2, "two"), expected_base_version=1,
        expected_corpus_revision=1,
    )
    return project_id


def restore_body(target=1, base=2, corpus=1, acknowledged=True) -> dict:
    body = {
        "target_version": target,
        "base_version": base,
        "corpus_revision": corpus,
    }
    if acknowledged is not None:
        body["acknowledged"] = acknowledged
    return body


class TestRestoreRoute:
    def test_restore_returns_201_valid_deck_version(self, client_db):
        client, conn = client_db
        project_id = seed_project_with_two_versions(client, conn)
        r = client.post(
            f"/api/v1/projects/{project_id}/restores",
            json=restore_body(),
            headers={"Idempotency-Key": "k-r1"},
        )
        assert r.status_code == 201
        version = r.json()
        js.validate(version, sub_schema("DeckVersion"))
        assert version["version"] == 3
        assert version["parent_version"] == 2
        assert version["restored_from"] == 1
        assert version["project_id"] == project_id

    def test_restore_missing_acknowledged_422(self, client_db):
        client, conn = client_db
        project_id = seed_project_with_two_versions(client, conn)
        r = client.post(
            f"/api/v1/projects/{project_id}/restores",
            json=restore_body(acknowledged=None),
            headers={"Idempotency-Key": "k-r2"},
        )
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_restore_acknowledged_false_422(self, client_db):
        client, conn = client_db
        project_id = seed_project_with_two_versions(client, conn)
        r = client.post(
            f"/api/v1/projects/{project_id}/restores",
            json=restore_body(acknowledged=False),
            headers={"Idempotency-Key": "k-r3"},
        )
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_restore_unknown_project_404(self, client_db):
        client, conn = client_db
        r = client.post(
            "/api/v1/projects/prj_missing/restores",
            json=restore_body(),
            headers={"Idempotency-Key": "k-r4"},
        )
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "PROJECT_NOT_FOUND"

    def test_restore_missing_target_404(self, client_db):
        client, conn = client_db
        project_id = seed_project_with_two_versions(client, conn)
        r = client.post(
            f"/api/v1/projects/{project_id}/restores",
            json=restore_body(target=9),
            headers={"Idempotency-Key": "k-r5"},
        )
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "DECK_NOT_FOUND"

    def test_restore_stale_base_409_version_conflict(self, client_db):
        client, conn = client_db
        project_id = seed_project_with_two_versions(client, conn)
        r = client.post(
            f"/api/v1/projects/{project_id}/restores",
            json=restore_body(base=1),
            headers={"Idempotency-Key": "k-r6"},
        )
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "VERSION_CONFLICT"
        project = client.get(f"/api/v1/projects/{project_id}").json()
        assert project["current_version"] == 2

    def test_restore_cross_corpus_409_corpus_changed(self, client_db):
        client, conn = client_db
        project_id = seed_project_with_two_versions(client, conn)
        with conn:
            conn.execute(
                "UPDATE projects SET corpus_revision = 2 WHERE id = ?", (project_id,)
            )
        r = client.post(
            f"/api/v1/projects/{project_id}/restores",
            json=restore_body(corpus=2),
            headers={"Idempotency-Key": "k-r7"},
        )
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "CORPUS_CHANGED"

    def test_restore_active_job_409_project_busy(self, client_db):
        client, conn = client_db
        project_id = seed_project_with_two_versions(client, conn)
        with conn:
            conn.execute(
                "UPDATE projects SET active_job_id = 'job_busy' WHERE id = ?",
                (project_id,),
            )
        r = client.post(
            f"/api/v1/projects/{project_id}/restores",
            json=restore_body(),
            headers={"Idempotency-Key": "k-r8"},
        )
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "PROJECT_BUSY"

    def test_restore_idempotent_replay_does_not_double_commit(self, client_db):
        client, conn = client_db
        project_id = seed_project_with_two_versions(client, conn)
        headers = {"Idempotency-Key": "k-r9"}
        first = client.post(
            f"/api/v1/projects/{project_id}/restores", json=restore_body(), headers=headers
        )
        second = client.post(
            f"/api/v1/projects/{project_id}/restores", json=restore_body(), headers=headers
        )
        assert first.status_code == 201
        assert second.status_code == 201
        assert second.json() == first.json()
        project = client.get(f"/api/v1/projects/{project_id}").json()
        assert project["current_version"] == 3

    def test_restore_same_key_different_body_409(self, client_db):
        client, conn = client_db
        project_id = seed_project_with_two_versions(client, conn)
        headers = {"Idempotency-Key": "k-r10"}
        first = client.post(
            f"/api/v1/projects/{project_id}/restores", json=restore_body(target=1), headers=headers
        )
        assert first.status_code == 201
        second = client.post(
            f"/api/v1/projects/{project_id}/restores",
            json=restore_body(target=1, base=3),
            headers=headers,
        )
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
