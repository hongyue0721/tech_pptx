import hashlib
from pathlib import Path

import pytest

from courseware_core.errors import DomainError, ProjectBusy, ProjectNotFound
from courseware_core.materials.parser import EXTRACTOR_VERSION
from courseware_core.services.material_service import (
    MaterialService,
    ProjectLimits,
)
from courseware_core.storage.database import connect
from courseware_core.storage.job_repository import JobRepository
from courseware_core.storage.material_repository import MaterialRepository

DEMO = Path(__file__).resolve().parents[3] / "demo-data"
NOTES_PDF = DEMO / "inputs" / "01_stm32_interrupt_notes.pdf"
CASES_PDF = DEMO / "inputs" / "02_priority_casebook.pdf"
ENCRYPTED_PDF = DEMO / "negative" / "encrypted.pdf"
MIXED_PDF = DEMO / "negative" / "mixed_text_scan.pdf"

TINY_LIMITS = ProjectLimits(
    max_file_bytes=1024 * 1024,
    max_files=5,
    max_project_bytes=10 * 1024 * 1024,
    max_project_pages=200,
    max_project_chars=500_000,
)


@pytest.fixture()
def svc(conn, insert_project, tmp_path):
    insert_project("prj_a")
    return MaterialService(
        conn, materials_root=tmp_path / "materials", limits=TINY_LIMITS
    )


def upload(svc, data: bytes, name: str = "notes.pdf", project_id: str = "prj_a"):
    return svc.upload(project_id=project_id, original_name=name, data=data)


def parse_and_finalize(svc, conn, accepted):
    """模拟 worker 完整执行：claim（running）→ handler → finalize（终态与释放锁同事务）。"""
    jobs = JobRepository(conn)
    job = jobs.claim_next("test_worker")
    assert job is not None and job.id == accepted.job_id
    ref = svc.handle_parse(job)
    jobs.finalize(job.id, "succeeded", result_ref=ref)
    return ref


def test_upload_creates_queued_material_job_and_holds_lock(svc, conn, project_columns):
    accepted = upload(svc, NOTES_PDF.read_bytes())
    assert accepted.duplicate is False
    assert accepted.material_id and accepted.job_id
    material = MaterialRepository(conn).get(accepted.material_id)
    assert material.status == "queued"
    assert material.sha256 == hashlib.sha256(NOTES_PDF.read_bytes()).hexdigest()
    job = JobRepository(conn).get(accepted.job_id)
    assert job.kind == "parse" and job.status == "queued"
    # N1 收口：占锁+建 material+建 job 同事务，锁指向该 job
    assert project_columns("prj_a")["active_job_id"] == accepted.job_id
    stored = svc.material_path(accepted.material_id)
    assert stored.read_bytes() == NOTES_PDF.read_bytes()


def test_duplicate_same_sha_returns_original_material(svc, conn):
    first = upload(svc, NOTES_PDF.read_bytes(), "a.pdf")
    second = upload(svc, NOTES_PDF.read_bytes(), "renamed.pdf")
    assert second.duplicate is True
    assert second.material_id == first.material_id
    assert second.job_id is None
    rows = conn.execute("SELECT COUNT(*) c FROM materials").fetchone()["c"]
    assert rows == 1
    assert conn.execute("SELECT corpus_revision FROM projects").fetchone()[0] == 0


def test_duplicate_wins_over_file_count_limit(svc, conn):
    """B1 回归：配额满时重传已存在内容必须命中去重（重复不消费配额）。"""
    payload = b"%PDF-1.4\nunique base\n%%EOF"
    first = None
    for i in range(TINY_LIMITS.max_files):
        accepted = upload(svc, payload + f"u{i}".encode(), f"f{i}.pdf")
        if i == 0:
            first = accepted
        with conn:
            conn.execute("UPDATE projects SET active_job_id = NULL WHERE id = 'prj_a'")
    dup = upload(svc, payload + b"u0", "again.pdf")
    assert dup.duplicate is True
    assert dup.material_id == first.material_id
    assert conn.execute("SELECT COUNT(*) c FROM materials").fetchone()["c"] == TINY_LIMITS.max_files


def test_failed_material_reupload_starts_new_round(svc, conn):
    """N5 回归：failed 材料不算 duplicate，重传同内容重新走解析。"""
    data = ENCRYPTED_PDF.read_bytes()
    accepted = upload(svc, data, "enc.pdf")
    jobs = JobRepository(conn)
    job = jobs.claim_next("w1")
    with pytest.raises(DomainError):
        svc.handle_parse(job)
    jobs.finalize(job.id, "failed")
    assert MaterialRepository(conn).get(accepted.material_id).status == "failed"
    retry = upload(svc, data, "enc-retry.pdf")
    assert retry.duplicate is False
    assert retry.material_id != accepted.material_id
    assert retry.job_id is not None


def test_parse_io_error_marks_material_failed_not_zombie(svc, conn):
    """N3 回归：非 DomainError（如原件丢失）也必须把 material 收口为 failed。"""
    accepted = upload(svc, NOTES_PDF.read_bytes())
    job = JobRepository(conn).claim_next("w1")
    svc.material_path(accepted.material_id).unlink()
    with pytest.raises(Exception):
        svc.handle_parse(job)
    assert MaterialRepository(conn).get(accepted.material_id).status == "failed"
    assert MaterialRepository(conn).get(accepted.material_id).error_code == "INTERNAL_ERROR"


def test_upload_rejects_non_pdf_magic(svc):
    with pytest.raises(DomainError) as exc:
        upload(svc, b"hello, not a pdf")
    assert exc.value.code == "UNSUPPORTED_FILE"


def test_upload_rejects_oversize_file(svc):
    payload = b"%PDF-" + b"x" * (TINY_LIMITS.max_file_bytes + 1)
    with pytest.raises(DomainError) as exc:
        upload(svc, payload)
    assert exc.value.code == "PAYLOAD_TOO_LARGE"


def test_upload_rejects_when_project_full_of_files(svc, conn):
    payload = b"%PDF-1.4\nnot really parseable but passes magic check\n%%EOF"
    for i in range(TINY_LIMITS.max_files):
        accepted = upload(svc, payload + f"unique{i}".encode(), f"f{i}.pdf")
        # 释放项目锁以便下一次上传（本用例验证份数限额，不验证锁）
        with conn:
            conn.execute(
                "UPDATE projects SET active_job_id = NULL WHERE id = 'prj_a'"
            )
    with pytest.raises(DomainError) as exc:
        upload(svc, payload + b"unique6", "f6.pdf")
    assert exc.value.code == "PAYLOAD_TOO_LARGE"


def test_upload_busy_project_raises_project_busy(svc, conn):
    conn.execute("UPDATE projects SET active_job_id = 'other_job' WHERE id = 'prj_a'")
    conn.commit()
    with pytest.raises(ProjectBusy):
        upload(svc, NOTES_PDF.read_bytes())
    rows = conn.execute("SELECT COUNT(*) c FROM materials").fetchone()["c"]
    assert rows == 0


def test_upload_missing_project_raises(svc):
    with pytest.raises(ProjectNotFound):
        upload(svc, NOTES_PDF.read_bytes(), project_id="ghost")


def test_filename_is_escaped_and_never_used_as_path(svc, conn):
    accepted = upload(svc, NOTES_PDF.read_bytes(), name="../../etc/passwd.pdf")
    material = MaterialRepository(conn).get(accepted.material_id)
    assert "/" not in material.original_name
    assert ".." not in material.original_name
    stored = svc.material_path(accepted.material_id)
    assert stored.is_file()
    assert stored.resolve().is_relative_to(svc.materials_root.resolve())


def test_parse_flow_marks_ready_and_bumps_corpus(svc, conn):
    accepted = upload(svc, NOTES_PDF.read_bytes())
    job = JobRepository(conn).get(accepted.job_id)
    ref = svc.handle_parse(job)
    assert ref.type == "material" and ref.id == accepted.material_id
    material = MaterialRepository(conn).get(accepted.material_id)
    assert material.status == "ready"
    assert material.pdf_pages >= 1
    assert material.usable_pages >= 1
    assert material.corpus_revision == 1
    assert conn.execute("SELECT corpus_revision FROM projects").fetchone()[0] == 1
    pages = conn.execute(
        "SELECT COUNT(*) c FROM pages WHERE document_id = ?", (accepted.material_id,)
    ).fetchone()["c"]
    assert pages == material.pdf_pages
    chunks = conn.execute(
        "SELECT COUNT(*) c FROM chunks WHERE document_id = ?", (accepted.material_id,)
    ).fetchone()["c"]
    assert chunks >= 1


def test_parsed_page_offsets_and_hashes_hold(svc, conn):
    accepted = upload(svc, NOTES_PDF.read_bytes())
    job = JobRepository(conn).get(accepted.job_id)
    svc.handle_parse(job)
    rows = conn.execute(
        "SELECT c.page_start, c.page_end, c.text, c.text_sha256,"
        " p.text AS page_text FROM chunks c JOIN pages p"
        " ON p.document_id = c.document_id AND p.pdf_page = c.pdf_page"
        " WHERE c.document_id = ?",
        (accepted.material_id,),
    ).fetchall()
    assert rows
    for r in rows:
        assert r["page_text"][r["page_start"] : r["page_end"]] == r["text"]
        assert hashlib.sha256(r["text"].encode()).hexdigest() == r["text_sha256"]


def test_parse_encrypted_marks_material_failed(svc, conn):
    accepted = upload(svc, ENCRYPTED_PDF.read_bytes(), "enc.pdf")
    job = JobRepository(conn).get(accepted.job_id)
    with pytest.raises(DomainError) as exc:
        svc.handle_parse(job)
    assert exc.value.code == "PDF_ENCRYPTED"
    material = MaterialRepository(conn).get(accepted.material_id)
    assert material.status == "failed"
    assert material.error_code == "PDF_ENCRYPTED"
    assert conn.execute("SELECT corpus_revision FROM projects").fetchone()[0] == 0


def test_parse_mixed_keeps_ready_with_page_warnings(svc, conn):
    accepted = upload(svc, MIXED_PDF.read_bytes(), "mixed.pdf")
    job = JobRepository(conn).get(accepted.job_id)
    svc.handle_parse(job)
    material = MaterialRepository(conn).get(accepted.material_id)
    assert material.status == "ready"
    assert material.pdf_pages == 2 and material.usable_pages == 1
    codes = {w.code for w in material.warnings}
    assert codes == {"SCAN_DETECTED"}


def test_second_material_increments_corpus_again(svc, conn):
    a = upload(svc, NOTES_PDF.read_bytes())
    parse_and_finalize(svc, conn, a)
    b = upload(svc, CASES_PDF.read_bytes(), "cases.pdf")
    parse_and_finalize(svc, conn, b)
    assert conn.execute("SELECT corpus_revision FROM projects").fetchone()[0] == 2
    assert MaterialRepository(conn).get(b.material_id).corpus_revision == 2


def test_list_materials_returns_contract_shape(svc):
    a = upload(svc, NOTES_PDF.read_bytes())
    ml = svc.list_materials("prj_a")
    assert ml.corpus_revision == 0
    assert [m.id for m in ml.materials] == [a.material_id]


def test_parse_page_budget_exceeded_fails(svc, conn, insert_project):
    big = ProjectLimits(
        max_file_bytes=10 * 1024 * 1024,
        max_files=5,
        max_project_bytes=100 * 1024 * 1024,
        max_project_pages=1,
        max_project_chars=500_000,
    )
    svc._limits = big
    accepted = upload(svc, NOTES_PDF.read_bytes())
    job = JobRepository(conn).get(accepted.job_id)
    with pytest.raises(DomainError) as exc:
        svc.handle_parse(job)
    assert exc.value.code == "PAGE_LIMIT_EXCEEDED"


def test_extractor_version_recorded(svc, conn):
    accepted = upload(svc, NOTES_PDF.read_bytes())
    svc.handle_parse(JobRepository(conn).get(accepted.job_id))
    row = conn.execute(
        "SELECT extractor_version FROM pages WHERE document_id = ? LIMIT 1",
        (accepted.material_id,),
    ).fetchone()
    assert row["extractor_version"] == EXTRACTOR_VERSION


class TestParseExecutionStateR00:
    """R00-D：parse 真实 stage 上报与保存前取消检查。"""

    def test_cancel_requested_fails_fast_before_store(self, svc, conn):
        # 取消位已置：不得再执行昂贵的切块入库（corpus 不推进）。
        from courseware_core.errors import JobCancelled

        upload(svc, NOTES_PDF.read_bytes())
        jobs = JobRepository(conn)
        job = jobs.claim_next("w1")
        jobs.request_cancel(job.id)
        with pytest.raises(JobCancelled):
            svc.handle_parse(job)
        assert conn.execute("SELECT corpus_revision FROM projects").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) c FROM chunks").fetchone()["c"] == 0

    def test_parse_reports_parsing_stage(self, svc, conn, monkeypatch):
        import courseware_core.services.material_service as ms

        upload(svc, NOTES_PDF.read_bytes())
        jobs = JobRepository(conn)
        job = jobs.claim_next("w1")
        seen = {}
        real = ms.parse_pdf

        def spy(*args, **kwargs):
            seen["stage"] = conn.execute(
                "SELECT stage FROM jobs WHERE id = ?", (job.id,)
            ).fetchone()["stage"]
            return real(*args, **kwargs)

        monkeypatch.setattr(ms, "parse_pdf", spy)
        svc.handle_parse(job)
        assert seen["stage"] == "parsing"  # 领取后 stage 不得停在 queued（真实进度）
