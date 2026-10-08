"""变体不特判（T06 验收 4 / docs/05 §49）：改名、重排页序后重新检索并更新页码，
系统内不存在按文件名/特定词/已知课题匹配预制答案的逻辑。"""

import sqlite3
from pathlib import Path

import pytest

from courseware_core.retrieval.bm25 import search_chunks
from courseware_core.services.material_service import MaterialService
from courseware_core.storage.database import connect, init_db
from courseware_core.storage.job_repository import JobRepository

DEMO = Path(__file__).resolve().parents[3] / "demo-data"
VARIANT = DEMO / "variants" / "renamed_reordered_notes.pdf"

T0 = "2026-09-19T00:00:00+00:00"


@pytest.fixture()
def variant_project(tmp_path):
    db = tmp_path / "var.db"
    conn = connect(db)
    init_db(conn)
    with conn:
        conn.execute(
            "INSERT INTO projects (id, course_json, current_version, corpus_revision,"
            " active_job_id, consent_to_cloud_processing, created_at, updated_at)"
            " VALUES ('prj_v', ?, 0, 0, NULL, 1, ?, ?)",
            (
                '{"topic": "t", "audience": "a", "duration_minutes": 45,'
                ' "goals": ["g"], "target_slides": 8}',
                T0,
                T0,
            ),
        )
    svc = MaterialService(conn, materials_root=tmp_path / "materials")
    accepted = svc.upload(
        project_id="prj_v", original_name="随便起的名字.pdf", data=VARIANT.read_bytes()
    )
    job = JobRepository(conn).get(accepted.job_id)
    svc.handle_parse(job)
    JobRepository(conn).finalize(job.id, "succeeded")
    yield conn
    conn.close()


def test_variant_renamed_still_retrievable(variant_project):
    hits = search_chunks(
        variant_project,
        project_id="prj_v",
        corpus_revision=1,
        query="NVIC 优先级分组",
        limit=12,
    )
    assert hits, "改名后的变体材料必须与原名材料走同一检索路径命中"


def test_page_numbers_follow_variant_physical_pages(variant_project):
    """重排页序后命中页码反映变体自己的物理页，不沿用原件页码。"""
    hits = search_chunks(
        variant_project,
        project_id="prj_v",
        corpus_revision=1,
        query="NVIC 优先级分组",
        limit=12,
    )
    top = hits[0]
    row = variant_project.execute(
        "SELECT c.text, p.text AS page_text FROM chunks c"
        " JOIN pages p ON p.document_id = c.document_id AND p.pdf_page = c.pdf_page"
        " WHERE c.chunk_id = ?",
        (top.chunk_id,),
    ).fetchone()
    assert row["page_text"][top.page_start : top.page_end] == row["text"]
    # 该页确实是命中内容所在的物理页（page 表按变体抽取重建）
    assert "优先级" in row["page_text"]


def test_document_name_is_display_only(variant_project):
    """检索与定位结果不携带也不依赖原始文件名的语义。"""
    hits = search_chunks(
        variant_project,
        project_id="prj_v",
        corpus_revision=1,
        query="NVIC",
        limit=5,
    )
    assert all(h.project_id == "prj_v" for h in hits)
