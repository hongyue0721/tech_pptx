"""F00 最小读接口契约：GET deck / GET evidence（零模型调用、只读）。

范围（AGENT_00 第二轮 + API_UI_MATRIX）：
- deck：缺省版本取 project.current_version；0/无正式版本 → 404 DECK_NOT_FOUND；
  版本必须是该项目实际记录，不按目录文件名猜测；跨项目 404。
- evidence：chunk 属于当前项目且在所请求的累积 revision 内；拒绝超前 revision
  （409 CORPUS_CHANGED）与跨项目/超范围访问（404 EVIDENCE_NOT_FOUND）；
  返回服务器定位过的 DocumentChunk（物理页码，打印页码标签独立字段）。
"""

import hashlib
import json

from fastapi.testclient import TestClient

from courseware_api.main import create_app
from courseware_core.models import CourseBrief, DeckSpec, Slide
from courseware_core.storage.database import connect, init_db

T0 = "2026-09-19T00:00:00+00:00"
COURSE = CourseBrief(
    topic="STM32 中断", audience="大二", duration_minutes=45,
    goals=["理解 NVIC 分组"], target_slides=8,
)


def app_client(db_path):
    return TestClient(create_app(db_path))


def seed_project(conn, project_id, *, current_version=0, corpus_revision=1):
    with conn:
        conn.execute(
            "INSERT INTO projects (id, course_json, current_version,"
            " corpus_revision, active_job_id, consent_to_cloud_processing,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, NULL, 1, ?, ?)",
            (project_id, COURSE.model_dump_json(), current_version,
             corpus_revision, T0, T0),
        )


def seed_deck_version(conn, project_id, version, corpus_revision=1):
    deck = DeckSpec(
        schema_version="1.0.0", project_id=project_id, version=version,
        corpus_revision=corpus_revision, course=COURSE, claims=[],
        slides=[Slide(id="ps1", title="NVIC分组", layout="concept",
                      blocks=[{"type": "teaching", "text": "先分组再设数值。"}])],
    )
    sha = hashlib.sha256(deck.model_dump_json().encode()).hexdigest()
    with conn:
        conn.execute(
            "INSERT INTO deck_versions (project_id, version, corpus_revision,"
            " parent_version, restored_from, created_at, content_sha256,"
            " deck_json) VALUES (?, ?, ?, ?, NULL, ?, ?, ?)",
            (project_id, version, corpus_revision, version - 1, T0, sha,
             deck.model_dump_json()),
        )


def seed_chunk(conn, project_id, chunk_id, *, corpus_revision=1, text="NVIC 优先级分组通过 AIRCR 配置。"):
    with conn:
        conn.execute(
            "INSERT INTO materials (id, project_id, original_name, sha256,"
            " status, pdf_pages, usable_pages, corpus_revision, warnings_json,"
            " error_code, file_path, file_size, job_id, created_at, updated_at)"
            " VALUES (?, ?, '讲义.pdf', ?, 'ready', 1, 1, ?, '[]', NULL,"
            " 'x.pdf', 100, NULL, ?, ?)",
            (f"mat_{project_id}", project_id, "a" * 64, corpus_revision, T0, T0),
        )
        conn.execute(
            "INSERT INTO chunks (chunk_id, project_id, document_id,"
            " corpus_revision, pdf_page, page_start, page_end, text,"
            " text_sha256, extractor_version, tokenizer_version)"
            " VALUES (?, ?, ?, ?, 2, 0, ?, ?, ?, 'pypdf-5.9.0-nfc-v1',"
            " 'jieba-0.42.1+ascii-v1')",
            (chunk_id, project_id, f"mat_{project_id}", corpus_revision,
             len(text), text, hashlib.sha256(text.encode()).hexdigest()),
        )


class TestDeckRead:
    def test_no_official_version_404(self, tmp_path):
        db = tmp_path / "d0.db"
        conn = connect(db)
        init_db(conn)
        seed_project(conn, "prjA", current_version=0)
        conn.close()
        client = app_client(db)
        with client:
            r = client.get("/api/v1/projects/prjA/deck")
            assert r.status_code == 404
            assert r.json()["error"]["code"] == "DECK_NOT_FOUND"

    def test_default_reads_current_version(self, tmp_path):
        db = tmp_path / "d1.db"
        conn = connect(db)
        init_db(conn)
        seed_project(conn, "prjA", current_version=2)
        seed_deck_version(conn, "prjA", 1)
        seed_deck_version(conn, "prjA", 2)
        conn.close()
        client = app_client(db)
        with client:
            r = client.get("/api/v1/projects/prjA/deck")
            assert r.status_code == 200
            assert r.json()["version"] == 2
            assert r.json()["project_id"] == "prjA"

    def test_explicit_version_and_missing_version(self, tmp_path):
        db = tmp_path / "d2.db"
        conn = connect(db)
        init_db(conn)
        seed_project(conn, "prjA", current_version=1)
        seed_deck_version(conn, "prjA", 1)
        conn.close()
        client = app_client(db)
        with client:
            r = client.get("/api/v1/projects/prjA/deck?version=1")
            assert r.status_code == 200
            assert r.json()["version"] == 1
            r = client.get("/api/v1/projects/prjA/deck?version=9")
            assert r.status_code == 404
            assert r.json()["error"]["code"] == "DECK_NOT_FOUND"
            # version=0：契约 minimum=1，但按 404 DECK_NOT_FOUND 语义处理
            # （"没有正式版本"），不泄漏成 422 参数错误。
            r = client.get("/api/v1/projects/prjA/deck?version=0")
            assert r.status_code == 404
            assert r.json()["error"]["code"] == "DECK_NOT_FOUND"

    def test_cross_project_version_404(self, tmp_path):
        db = tmp_path / "d3.db"
        conn = connect(db)
        init_db(conn)
        seed_project(conn, "prjA", current_version=1)
        seed_project(conn, "prjB", current_version=1)
        seed_deck_version(conn, "prjA", 1)
        conn.close()
        client = app_client(db)
        with client:
            r = client.get("/api/v1/projects/prjB/deck?version=1")
            assert r.status_code == 404
            assert r.json()["error"]["code"] == "DECK_NOT_FOUND"

    def test_unknown_project_404(self, tmp_path):
        db = tmp_path / "d4.db"
        client = app_client(db)
        with client:
            r = client.get("/api/v1/projects/ghost/deck")
            assert r.status_code == 404
            assert r.json()["error"]["code"] == "PROJECT_NOT_FOUND"


class TestEvidenceRead:
    def test_returns_server_located_chunk(self, tmp_path):
        db = tmp_path / "e1.db"
        conn = connect(db)
        init_db(conn)
        seed_project(conn, "prjA", corpus_revision=1)
        seed_chunk(conn, "prjA", "chk1")
        conn.close()
        client = app_client(db)
        with client:
            r = client.get("/api/v1/projects/prjA/evidence/chk1?corpus_revision=1")
            assert r.status_code == 200
            body = r.json()
            assert body["chunk_id"] == "chk1"
            assert body["document_name"] == "讲义.pdf"
            assert body["pdf_page"] == 2  # 物理页码（服务器记录，非模型自填）
            assert body["text"].startswith("NVIC")

    def test_future_revision_rejected_409(self, tmp_path):
        db = tmp_path / "e2.db"
        conn = connect(db)
        init_db(conn)
        seed_project(conn, "prjA", corpus_revision=1)
        seed_chunk(conn, "prjA", "chk1")
        conn.close()
        client = app_client(db)
        with client:
            r = client.get("/api/v1/projects/prjA/evidence/chk1?corpus_revision=9")
            assert r.status_code == 409
            assert r.json()["error"]["code"] == "CORPUS_CHANGED"

    def test_chunk_outside_requested_snapshot_404(self, tmp_path):
        # chunk 属项目但产生于 revision 2：按 revision 1 的累积快照读不到。
        db = tmp_path / "e3.db"
        conn = connect(db)
        init_db(conn)
        seed_project(conn, "prjA", corpus_revision=2)
        seed_chunk(conn, "prjA", "chk2", corpus_revision=2)
        conn.close()
        client = app_client(db)
        with client:
            r = client.get("/api/v1/projects/prjA/evidence/chk2?corpus_revision=1")
            assert r.status_code == 404
            assert r.json()["error"]["code"] == "EVIDENCE_NOT_FOUND"
            r = client.get("/api/v1/projects/prjA/evidence/chk2?corpus_revision=2")
            assert r.status_code == 200

    def test_cross_project_chunk_404(self, tmp_path):
        db = tmp_path / "e4.db"
        conn = connect(db)
        init_db(conn)
        seed_project(conn, "prjA", corpus_revision=1)
        seed_project(conn, "prjB", corpus_revision=1)
        seed_chunk(conn, "prjA", "chk1")
        conn.close()
        client = app_client(db)
        with client:
            r = client.get("/api/v1/projects/prjB/evidence/chk1?corpus_revision=1")
            assert r.status_code == 404
            assert r.json()["error"]["code"] == "EVIDENCE_NOT_FOUND"

    def test_unknown_chunk_404(self, tmp_path):
        db = tmp_path / "e5.db"
        conn = connect(db)
        init_db(conn)
        seed_project(conn, "prjA", corpus_revision=1)
        conn.close()
        client = app_client(db)
        with client:
            r = client.get("/api/v1/projects/prjA/evidence/chk_ghost?corpus_revision=1")
            assert r.status_code == 404
            assert r.json()["error"]["code"] == "EVIDENCE_NOT_FOUND"

    def test_error_body_has_request_id(self, tmp_path):
        db = tmp_path / "e6.db"
        client = app_client(db)
        with client:
            r = client.get("/api/v1/projects/ghost/evidence/chk1?corpus_revision=1")
            assert r.status_code == 404
            assert r.json()["error"]["request_id"]
