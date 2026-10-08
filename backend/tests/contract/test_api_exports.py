"""T10 循环②：POST /projects/{id}/exports 与 GET artifacts download 契约测试。"""

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from courseware_core.models import DeckSpec
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


import jsonschema as js

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


def deck_payload(version: int) -> DeckSpec:
    return DeckSpec(
        schema_version="1.0.0",
        project_id="unused",
        version=version,
        corpus_revision=1,
        course=PROJECT_BODY["course"],
        claims=[],
        slides=[
            {
                "id": "sld_001",
                "title": f"页 v{version}",
                "layout": "title",
                "blocks": [{"type": "teaching", "text": "内容"}],
            }
        ],
    )


@pytest.fixture()
def client_db(tmp_path):
    from courseware_api.main import create_app

    db_path = tmp_path / "data" / "app.db"
    app = create_app(db_path, artifacts_root=tmp_path / "artifacts")
    conn = connect(db_path)
    with TestClient(app) as c:
        yield c, conn, db_path
    conn.close()


def seed_committed_project(client, conn) -> str:
    r = client.post(
        "/api/v1/projects", json=PROJECT_BODY, headers={"Idempotency-Key": "k-seed-x"}
    )
    assert r.status_code == 201
    project_id = r.json()["id"]
    with conn:
        conn.execute(
            "UPDATE projects SET corpus_revision = 1 WHERE id = ?", (project_id,)
        )
    from courseware_core.storage.version_repository import VersionRepository

    deck = deck_payload(1).model_copy(update={"project_id": project_id})
    VersionRepository(conn).commit_version(
        project_id, deck, expected_base_version=0, expected_corpus_revision=1
    )
    return project_id


def export_body(version: int = 1) -> dict:
    return {"version": version, "format": "pptx"}


class TestCreateExportJob:
    def test_returns_202_job_accepted(self, client_db):
        client, conn, _ = client_db
        project_id = seed_committed_project(client, conn)
        r = client.post(
            f"/api/v1/projects/{project_id}/exports",
            json=export_body(1),
            headers={"Idempotency-Key": "k-e1"},
        )
        assert r.status_code == 202
        js.validate(r.json(), sub_schema("JobAccepted"))
        job = client.get(f"/api/v1/jobs/{r.json()['job_id']}")
        assert job.status_code == 200
        assert job.json()["kind"] == "export"
        assert job.json()["status"] == "queued"
        assert job.json()["base_version"] == 1

    def test_idempotent_replay_same_job(self, client_db):
        client, conn, _ = client_db
        project_id = seed_committed_project(client, conn)
        headers = {"Idempotency-Key": "k-e2"}
        a = client.post(
            f"/api/v1/projects/{project_id}/exports", json=export_body(1), headers=headers
        )
        b = client.post(
            f"/api/v1/projects/{project_id}/exports", json=export_body(1), headers=headers
        )
        assert a.status_code == 202 and b.status_code == 202
        assert a.json()["job_id"] == b.json()["job_id"]

    def test_same_key_different_payload_conflicts(self, client_db):
        client, conn, _ = client_db
        project_id = seed_committed_project(client, conn)
        headers = {"Idempotency-Key": "k-e3"}
        client.post(
            f"/api/v1/projects/{project_id}/exports", json=export_body(1), headers=headers
        )
        r = client.post(
            f"/api/v1/projects/{project_id}/exports",
            json=export_body(2),
            headers=headers,
        )
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    def test_missing_version_404_deck_not_found(self, client_db):
        client, conn, _ = client_db
        project_id = seed_committed_project(client, conn)
        r = client.post(
            f"/api/v1/projects/{project_id}/exports",
            json=export_body(99),
            headers={"Idempotency-Key": "k-e4"},
        )
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "DECK_NOT_FOUND"

    def test_unsupported_format_422(self, client_db):
        client, conn, _ = client_db
        project_id = seed_committed_project(client, conn)
        r = client.post(
            f"/api/v1/projects/{project_id}/exports",
            json={"version": 1, "format": "pdf"},
            headers={"Idempotency-Key": "k-e5"},
        )
        assert r.status_code == 422

    def test_missing_project_404(self, client_db):
        client, conn, _ = client_db
        r = client.post(
            "/api/v1/projects/prj_missing/exports",
            json=export_body(1),
            headers={"Idempotency-Key": "k-e6"},
        )
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "PROJECT_NOT_FOUND"

    def test_corrupt_version_fails_explicit_code_not_internal(self, client_db):
        # 库里 committed 内容损坏=服务端数据完整性失败（与 ARTIFACT_INTEGRITY 同族
        # 500），但错误码必须显式 EXPORT_FAILED——不得退化为无信息的 INTERNAL_ERROR
        #（复审 N4：注释/映射/测试三者对齐，拒绝隐式 500 兜底）。
        client, conn, _ = client_db
        project_id = seed_committed_project(client, conn)
        with conn:
            conn.execute(
                "UPDATE deck_versions SET deck_json='{\"broken\": true}'"
                " WHERE project_id=? AND version=1",
                (project_id,),
            )
            assert conn.execute("SELECT changes() AS n").fetchone()["n"] == 1
        r = client.post(
            f"/api/v1/projects/{project_id}/exports",
            json=export_body(1),
            headers={"Idempotency-Key": "k-e7"},
        )
        assert r.status_code == 500
        assert r.json()["error"]["code"] == "EXPORT_FAILED"
    def _export(self, client, conn, project_id, tmp_path):
        from courseware_core.services.export_service import ExportService

        svc = ExportService(conn, artifacts_root=tmp_path / "artifacts")
        job = svc.create_export_job(project_id, _req(1))
        with conn:
            conn.execute(
                "UPDATE jobs SET status='running', worker_id='w_test' WHERE id=?", (job.id,)
            )
            assert conn.execute("SELECT changes() AS n").fetchone()["n"] == 1
        artifact_id = svc.handle_export(job.id)
        return artifact_id

    def test_download_headers_and_bytes(self, client_db, tmp_path):
        client, conn, db_path = client_db
        project_id = seed_committed_project(client, conn)
        artifact_id = self._export(client, conn, project_id, tmp_path)
        r = client.get(
            f"/api/v1/projects/{project_id}/artifacts/{artifact_id}/download"
        )
        assert r.status_code == 200
        assert r.content[:2] == b"PK"
        assert r.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument"
        )
        disposition = r.headers["content-disposition"]
        assert "attachment" in disposition and ".pptx" in disposition
        assert r.headers["x-artifact-sha256"] == hashlib.sha256(r.content).hexdigest()

    def test_report_artifact_downloadable_by_derived_id(self, client_db, tmp_path):
        # 前端按 api.md 契约规则 art_{job后缀}_report 派生下载：派生规则必须由
        # 契约测试锁死（后端改格式即红），这是 N2 耦合风险的防线。
        client, conn, db_path = client_db
        project_id = seed_committed_project(client, conn)
        artifact_id = self._export(client, conn, project_id, tmp_path)
        assert artifact_id.endswith("_pptx")
        derived_report = artifact_id.removesuffix("_pptx") + "_report"
        r = client.get(
            f"/api/v1/projects/{project_id}/artifacts/{derived_report}/download"
        )
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/json"
        assert r.json()["version"] == 1

    def test_cross_project_artifact_404(self, client_db, tmp_path):
        client, conn, db_path = client_db
        pid_a = seed_committed_project(client, conn)
        # 第二个项目（不同幂等键）。
        body = dict(PROJECT_BODY)
        r2 = client.post(
            "/api/v1/projects", json=body, headers={"Idempotency-Key": "k-seed-y"}
        )
        pid_b = r2.json()["id"]
        from courseware_core.services.export_service import ExportService

        svc = ExportService(conn, artifacts_root=tmp_path / "artifacts")
        job = svc.create_export_job(pid_a, _req(1))
        with conn:
            conn.execute(
                "UPDATE jobs SET status='running', worker_id='w_test' WHERE id=?", (job.id,)
            )
            assert conn.execute("SELECT changes() AS n").fetchone()["n"] == 1
        artifact_id = svc.handle_export(job.id)
        r = client.get(
            f"/api/v1/projects/{pid_b}/artifacts/{artifact_id}/download"
        )
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "ARTIFACT_NOT_FOUND"

    def test_missing_artifact_404(self, client_db):
        client, conn, _ = client_db
        project_id = seed_committed_project(client, conn)
        r = client.get(
            f"/api/v1/projects/{project_id}/artifacts/art_ghost/download"
        )
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "ARTIFACT_NOT_FOUND"

    def test_tampered_file_fails_integrity(self, client_db, tmp_path):
        client, conn, db_path = client_db
        project_id = seed_committed_project(client, conn)
        artifact_id = self._export(client, conn, project_id, tmp_path)
        target = tmp_path / "artifacts" / project_id / artifact_id
        target.write_bytes(b"corrupted")
        r = client.get(
            f"/api/v1/projects/{project_id}/artifacts/{artifact_id}/download"
        )
        assert r.status_code == 500
        assert r.json()["error"]["code"] == "ARTIFACT_INTEGRITY"


def _req(version: int):
    from courseware_core.models.export import ExportRequest

    return ExportRequest(version=version, format="pptx")
