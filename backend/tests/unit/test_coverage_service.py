import sqlite3
from pathlib import Path

import pytest

from courseware_core.services.coverage_service import evaluate_goal_coverage
from courseware_core.services.material_service import MaterialService
from courseware_core.storage.database import connect
from courseware_core.storage.job_repository import JobRepository

DEMO = Path(__file__).resolve().parents[3] / "demo-data"
NOTES_PDF = DEMO / "inputs" / "01_stm32_interrupt_notes.pdf"

T0 = "2026-09-19T00:00:00+00:00"


@pytest.fixture()
def parsed_project(tmp_path):
    """用 T05 真实链路建语料：上传→解析→ready，corpus_revision=1。"""
    db = tmp_path / "cov.db"
    conn = connect(db)
    from courseware_core.storage.database import init_db

    init_db(conn)
    with conn:
        conn.execute(
            "INSERT INTO projects (id, course_json, current_version, corpus_revision,"
            " active_job_id, consent_to_cloud_processing, created_at, updated_at)"
            " VALUES ('prj_c', ?, 0, 0, NULL, 1, ?, ?)",
            (
                '{"topic": "STM32 中断", "audience": "大二", "duration_minutes": 45,'
                ' "goals": ["理解 NVIC 优先级分组"], "target_slides": 8}',
                T0,
                T0,
            ),
        )
    svc = MaterialService(conn, materials_root=tmp_path / "materials")
    accepted = svc.upload(project_id="prj_c", original_name="notes.pdf", data=NOTES_PDF.read_bytes())
    job = JobRepository(conn).get(accepted.job_id)
    svc.handle_parse(job)
    JobRepository(conn).finalize(job.id, "succeeded")
    yield conn, svc
    conn.close()


def test_supported_goal_gets_chunk_ids(parsed_project):
    conn, _ = parsed_project
    coverage = evaluate_goal_coverage(
        conn,
        project_id="prj_c",
        goals=["NVIC 优先级分组 抢占"],
    )
    assert len(coverage) == 1
    c = coverage[0]
    assert c.goal_index == 0
    assert c.status == "supported"
    assert c.chunk_ids


def test_unrelated_goal_is_unsupported_with_note(parsed_project):
    conn, _ = parsed_project
    coverage = evaluate_goal_coverage(
        conn,
        project_id="prj_c",
        goals=["脉冲星计时阵列引力波偏振的测量"],
    )
    assert coverage[0].status == "unsupported"
    assert coverage[0].chunk_ids == []
    assert coverage[0].note  # 缺口必须给教师可见说明


def test_goal_index_follows_input_order(parsed_project):
    conn, _ = parsed_project
    coverage = evaluate_goal_coverage(
        conn,
        project_id="prj_c",
        goals=["脉冲星计时阵列引力波偏振", "抢占优先级与子优先级"],
    )
    assert [c.goal_index for c in coverage] == [0, 1]
    assert coverage[1].status == "supported"


def test_coverage_binds_corpus_snapshot(parsed_project):
    conn, _ = parsed_project
    good = evaluate_goal_coverage(conn, project_id="prj_c", goals=["NVIC 优先级分组 抢占"])
    assert good[0].status == "supported"  # rev=1 快照含已入库材料
    with conn:
        conn.execute("UPDATE projects SET corpus_revision = 0 WHERE id = 'prj_c'")
    coverage = evaluate_goal_coverage(
        conn, project_id="prj_c", goals=["NVIC 优先级分组 抢占"]
    )
    # rev=0 快照没有任何材料：不得偷看未来 revision 才入库的内容
    assert coverage[0].status == "unsupported"


def test_single_relevant_chunk_stays_partial(tmp_path):
    """B1 关联回归：语料中仅一条真相关时不得判 supported。"""
    from courseware_core.storage.database import connect as _c, init_db as _i
    from courseware_core.storage.job_repository import JobRepository as _J
    import hashlib
    import sqlite3

    db = tmp_path / "one.db"
    conn = _c(db)
    _i(conn)
    T0 = "2026-09-19T00:00:00+00:00"
    with conn:
        conn.execute(
            "INSERT INTO projects (id, course_json, current_version, corpus_revision,"
            " active_job_id, consent_to_cloud_processing, created_at, updated_at)"
            " VALUES ('prj_o', ?, 0, 1, NULL, 1, ?, ?)",
            (
                '{"topic": "t", "audience": "a", "duration_minutes": 45,'
                ' "goals": ["g"], "target_slides": 8}',
                T0, T0,
            ),
        )
        conn.execute(
            "INSERT INTO materials (id, project_id, original_name, sha256, status,"
            " warnings_json, file_path, file_size, created_at, updated_at)"
            " VALUES ('doc_o', 'prj_o', 'o.pdf', ?, 'ready', '[]', 'o.pdf', 1, ?, ?)",
            ("a" * 64, T0, T0),
        )
        text = "熵是系统无序度的度量，热力学第二定律给出方向判据。"
        conn.execute(
            "INSERT INTO chunks (chunk_id, project_id, document_id, corpus_revision,"
            " pdf_page, page_start, page_end, text, text_sha256, extractor_version,"
            " tokenizer_version) VALUES ('chk_o1', 'prj_o', 'doc_o', 1, 1, 0, ?, ?, ?, 'e1', 't1')",
            (len(text), text, hashlib.sha256(text.encode()).hexdigest()),
        )
    coverage = evaluate_goal_coverage(conn, project_id="prj_o", goals=["熵 无序度 度量 判据"])
    assert coverage[0].status == "partial"
    assert len(coverage[0].chunk_ids) == 1
    conn.close()


def test_contract_shape(parsed_project):
    conn, _ = parsed_project
    coverage = evaluate_goal_coverage(conn, project_id="prj_c", goals=["NVIC"])
    for c in coverage:
        assert c.status in {"supported", "partial", "unsupported", "conflict"}
        assert len(c.note) <= 500
