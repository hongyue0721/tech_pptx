"""固定测试集上的检索命中率实测（docs/05 §47/§49）。

evaluation/cases.json 只在测试侧读取，绝不进运行时索引（AGENTS.md §8）。
报告真实计数，不把模板宣称当实测结果。
"""

import json
from pathlib import Path

import pytest

from courseware_core.retrieval.bm25 import search_chunks
from courseware_core.services.material_service import MaterialService
from courseware_core.storage.database import connect, init_db
from courseware_core.storage.job_repository import JobRepository
from courseware_core.storage.material_repository import MaterialRepository

DEMO = Path(__file__).resolve().parents[3] / "demo-data"
# 检索命中率底线：下调属于放宽验收，需负责人显式批准（review N4）。
HIT_RATE_FLOOR = 0.8
CASES = json.loads((DEMO / "evaluation" / "cases.json").read_text(encoding="utf-8"))
T0 = "2026-09-19T00:00:00+00:00"


@pytest.fixture(scope="module")
def corpus_conn(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("metrics")
    db = tmp / "m.db"
    conn = connect(db)
    init_db(conn)
    with conn:
        conn.execute(
            "INSERT INTO projects (id, course_json, current_version, corpus_revision,"
            " active_job_id, consent_to_cloud_processing, created_at, updated_at)"
            " VALUES ('prj_m', ?, 0, 0, NULL, 1, ?, ?)",
            (
                '{"topic": "t", "audience": "a", "duration_minutes": 45,'
                ' "goals": ["g"], "target_slides": 8}',
                T0,
                T0,
            ),
        )
    svc = MaterialService(conn, materials_root=tmp / "materials")
    jobs = JobRepository(conn)
    for name in ("01_stm32_interrupt_notes.pdf", "02_priority_casebook.pdf"):
        accepted = svc.upload(project_id="prj_m", original_name=name, data=(DEMO / "inputs" / name).read_bytes())
        job = jobs.claim_next("metrics_worker")
        assert job is not None and job.id == accepted.job_id
        svc.handle_parse(job)
        jobs.finalize(job.id, "succeeded")
    yield conn
    conn.close()


def test_retrieval_hit_rate_measured_not_claimed(corpus_conn, capsys):
    retrieval_cases = [c for c in CASES if c.get("category") == "retrieval"]
    assert retrieval_cases, "评测集必须含 retrieval 用例"
    doc_name_by_id = {
        m.id: m.original_name
        for m in MaterialRepository(corpus_conn).list_by_project("prj_m")
    }
    hits = 0
    misses: list[str] = []
    for case in retrieval_cases:
        relevant = {
            (p.split(":")[0], int(p.rsplit(":", 1)[1]))
            for p in case["relevant_pages"]
        }
        results = search_chunks(
            corpus_conn,
            project_id="prj_m",
            corpus_revision=2,
            query=case["input"],
            limit=8,
        )
        hit_pairs = {(doc_name_by_id[r.document_id], r.pdf_page) for r in results}
        if hit_pairs & relevant:
            hits += 1
        else:
            misses.append(case["id"])
    rate = hits / len(retrieval_cases)
    with capsys.disabled():
        print(f"\n[T06 实测] 检索命中率 {hits}/{len(retrieval_cases)} = {rate:.1%}，未命中: {misses}")
    assert rate >= HIT_RATE_FLOOR, f"实测命中率 {rate:.1%} 低于底线 {HIT_RATE_FLOOR:.0%}，未命中 {misses}"
