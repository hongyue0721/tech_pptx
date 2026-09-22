"""T10 循环③：GET /projects/{id}/versions/{version}/previews 契约测试。

P0 预览分级=OUTLINE（docs/08 §预览分级）：结构预览由前端按 DeckSpec 渲染，
manifest 只声明每页来源与状态，绝不冒充 PPTX 渲染图；预览失败不影响已提交
语义版本、不偷偷用旧图（artifact_id 恒空、failed 带 warning）。
"""

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


COURSE = {
    "topic": "STM32 中断",
    "audience": "大二",
    "duration_minutes": 45,
    "goals": ["理解 NVIC"],
    "target_slides": 8,
}


def deck_payload(version: int, slide_ids: list[str]) -> DeckSpec:
    return DeckSpec(
        schema_version="1.0.0",
        project_id="prj_x",
        version=version,
        corpus_revision=1,
        course=COURSE,
        claims=[],
        slides=[
            {
                "id": sid,
                "title": f"页 {sid}",
                "layout": "title",
                "blocks": [{"type": "teaching", "text": "内容"}],
            }
            for sid in slide_ids
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


def seed_two_versions(client, conn):
    r = client.post(
        "/api/v1/projects",
        json={"course": COURSE, "consent_to_cloud_processing": True},
        headers={"Idempotency-Key": "k-seed-p"},
    )
    project_id = r.json()["id"]
    with conn:
        conn.execute("UPDATE projects SET corpus_revision=1 WHERE id=?", (project_id,))
    versions = VersionRepository(conn)
    versions.commit_version(
        project_id,
        deck_payload(1, ["a1", "a2"]).model_copy(update={"project_id": project_id}),
        expected_base_version=0,
        expected_corpus_revision=1,
    )
    versions.commit_version(
        project_id,
        deck_payload(2, ["b1", "b2", "b3"]).model_copy(update={"project_id": project_id}),
        expected_base_version=1,
        expected_corpus_revision=1,
    )
    return project_id


class TestPreviewManifest:
    def test_outline_level_manifest(self, client_db):
        client, conn = client_db
        project_id = seed_two_versions(client, conn)
        r = client.get(f"/api/v1/projects/{project_id}/versions/2/previews")
        assert r.status_code == 200
        body = r.json()
        js.validate(body, sub_schema("PreviewManifest"))
        assert body["project_id"] == project_id
        assert body["version"] == 2
        assert [i["slide_id"] for i in body["items"]] == ["b1", "b2", "b3"]
        for item in body["items"]:
            # P0=OUTLINE 结构预览：不声明渲染图、不冒充更高保真等级。
            assert item["source_type"] == "outline"
            assert item["status"] == "ready"
            assert item["artifact_id"] is None

    def test_never_mix_versions(self, client_db):
        client, conn = client_db
        project_id = seed_two_versions(client, conn)
        r1 = client.get(f"/api/v1/projects/{project_id}/versions/1/previews")
        assert [i["slide_id"] for i in r1.json()["items"]] == ["a1", "a2"]

    def test_missing_version_404(self, client_db):
        client, conn = client_db
        project_id = seed_two_versions(client, conn)
        r = client.get(f"/api/v1/projects/{project_id}/versions/99/previews")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "DECK_NOT_FOUND"

    def test_missing_project_404(self, client_db):
        client, conn = client_db
        r = client.get("/api/v1/projects/prj_missing/versions/1/previews")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "PROJECT_NOT_FOUND"

    def test_version_zero_404(self, client_db):
        client, conn = client_db
        project_id = seed_two_versions(client, conn)
        r = client.get(f"/api/v1/projects/{project_id}/versions/0/previews")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "DECK_NOT_FOUND"

    def test_corrupt_deck_fails_honestly_not_ready(self, client_db):
        # 损坏行不得盖绿：items 全部 failed 带 warning，绝不返回假 ready。
        client, conn = client_db
        project_id = seed_two_versions(client, conn)
        with conn:
            conn.execute(
                "UPDATE deck_versions SET deck_json='{\"broken\": true}'"
                " WHERE project_id=? AND version=1",
                (project_id,),
            )
            assert conn.execute("SELECT changes() AS n").fetchone()["n"] == 1
        r = client.get(f"/api/v1/projects/{project_id}/versions/1/previews")
        assert r.status_code == 200
        body = r.json()
        js.validate(body, sub_schema("PreviewManifest"))
        assert all(i["status"] == "failed" and i["warning"] for i in body["items"])
