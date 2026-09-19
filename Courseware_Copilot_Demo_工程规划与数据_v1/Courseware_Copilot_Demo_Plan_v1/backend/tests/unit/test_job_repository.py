import pytest

from courseware_core.errors import JobNotFound
from courseware_core.models import ErrorDetail, ErrorResponse, Job, JobResultRef
from courseware_core.storage.job_repository import JobRepository

T0 = "2026-09-19T00:00:00+00:00"


def make_job(
    job_id: str = "job_1",
    project_id: str = "prj_a",
    status: str = "queued",
    stage: str = "queued",
    kind: str = "parse",
    created_at: str = T0,
    **overrides,
) -> Job:
    payload = dict(
        id=job_id,
        project_id=project_id,
        kind=kind,
        status=status,
        stage=stage,
        cancel_requested=False,
        base_version=0,
        corpus_revision=1,
        created_at=created_at,
        updated_at=T0,
    )
    payload.update(overrides)
    return Job(**payload)


def _err() -> ErrorResponse:
    return ErrorResponse(
        error=ErrorDetail(
            code="VALIDATION_ERROR", message="boom", request_id="req_x", details={}
        )
    )


@pytest.fixture()
def repo(conn, insert_project):
    insert_project("prj_a")
    return JobRepository(conn)


def test_create_and_get_roundtrip(repo):
    job = make_job()
    repo.create(job, request_id="req_1")
    assert repo.get("job_1") == job


def test_get_missing_returns_none(repo):
    assert repo.get("nope") is None


def test_claim_next_transitions_queued_to_running(repo):
    repo.create(make_job())
    claimed = repo.claim_next("w1")
    assert claimed is not None
    assert claimed.id == "job_1"
    assert claimed.status == "running"
    assert claimed.stage == "queued"
    assert repo.claim_next("w1") is None


def test_claim_respects_fifo_order(repo):
    repo.create(make_job("job_b", created_at="2026-01-01T00:00:00+00:00"))
    repo.create(make_job("job_a", created_at="2026-06-01T00:00:00+00:00"))
    claimed = repo.claim_next("w1")
    assert claimed.id == "job_b"


def test_request_cancel_queued_becomes_cancelled(repo):
    repo.create(make_job())
    job = repo.request_cancel("job_1")
    assert job.status == "cancelled"


def test_request_cancel_running_sets_flag(repo):
    repo.create(make_job(status="running", stage="parsing"))
    job = repo.request_cancel("job_1")
    assert job.status == "running"
    assert job.cancel_requested is True


def test_request_cancel_terminal_unchanged(repo):
    repo.create(make_job(status="succeeded", stage="finished"))
    job = repo.request_cancel("job_1")
    assert job.status == "succeeded"
    assert job.cancel_requested is False


def test_request_cancel_missing_returns_none(repo):
    assert repo.request_cancel("nope") is None


def test_mark_interrupted_on_startup_only_affects_running(repo, conn, insert_project):
    insert_project("prj_b")
    repo.create(make_job("job_r1", status="running", stage="parsing"))
    repo.create(make_job("job_r2", project_id="prj_b", status="running"))
    repo.create(make_job("job_q", status="queued"))
    interrupted = repo.mark_interrupted_on_startup()
    assert set(interrupted) == {"job_r1", "job_r2"}
    assert repo.get("job_r1").status == "interrupted"
    assert repo.get("job_q").status == "queued"


def test_mark_interrupted_releases_project_lock(repo, conn, project_columns):
    repo.create(make_job("job_r1", status="running"))
    with conn:
        conn.execute(
            "UPDATE projects SET active_job_id = 'job_r1' WHERE id = 'prj_a'"
        )
    repo.mark_interrupted_on_startup()
    assert project_columns("prj_a")["active_job_id"] is None


def test_finalize_succeeded_releases_own_lock(repo, conn, project_columns):
    repo.create(make_job("job_1", status="running"))
    with conn:
        conn.execute("UPDATE projects SET active_job_id = 'job_1' WHERE id = 'prj_a'")
    ref = JobResultRef(type="material", id="mat_9")
    done = repo.finalize("job_1", "succeeded", result_ref=ref)
    assert done.status == "succeeded"
    assert done.stage == "finished"
    assert done.result_ref == ref
    assert project_columns("prj_a")["active_job_id"] is None


def test_finalize_does_not_release_other_job_lock(repo, conn, project_columns):
    repo.create(make_job("job_1", status="running"))
    with conn:
        conn.execute("UPDATE projects SET active_job_id = 'other' WHERE id = 'prj_a'")
    repo.finalize("job_1", "failed", error=_err())
    assert project_columns("prj_a")["active_job_id"] == "other"


def test_finalize_failed_roundtrips_error(repo):
    repo.create(make_job("job_1", status="running"))
    done = repo.finalize("job_1", "failed", error=_err())
    assert done.status == "failed"
    assert done.error.error.code == "VALIDATION_ERROR"
    assert done.error.error.message == "boom"


def test_finalize_missing_raises(repo):
    with pytest.raises(JobNotFound):
        repo.finalize("nope", "succeeded")


def test_set_stage_updates_stage(repo):
    repo.create(make_job("job_1", status="running"))
    job = repo.set_stage("job_1", "retrieving")
    assert job.stage == "retrieving"
    assert job.status == "running"


def test_cancel_vs_claim_race_keeps_lock_invariant(tmp_path):
    """B1 回归：cancel 与 claim 真并发交错，反复 20 轮，锁与 job 状态必须始终一致——
    running 时锁必须仍被该 job 持有（不得被取消路径提前释放），
    cancelled 时锁必须已释放。"""
    import threading

    from courseware_core.storage.database import connect as _connect
    from courseware_core.storage.database import init_db as _init_db

    db = tmp_path / "race2.db"
    seed = _connect(db)
    _init_db(seed)
    with seed:
        seed.execute(
            "INSERT INTO projects (id, course_json, current_version, corpus_revision,"
            " active_job_id, consent_to_cloud_processing, created_at, updated_at)"
            " VALUES ('prj_a', '{}', 0, 1, 'job_1', 1, ?, ?)",
            (T0, T0),
        )
    JobRepository(seed).create(make_job("job_1", status="queued"))
    seed.close()

    for _ in range(20):
        conn = _connect(db)
        with conn:
            conn.execute(
                "UPDATE jobs SET status = 'queued', stage = 'queued',"
                " cancel_requested = 0 WHERE id = 'job_1'"
            )
            conn.execute(
                "UPDATE projects SET active_job_id = 'job_1' WHERE id = 'prj_a'"
            )
        conn.close()

        barrier = threading.Barrier(2)

        def cancel():
            c = _connect(db)
            try:
                barrier.wait()
                JobRepository(c).request_cancel("job_1")
            finally:
                c.close()

        def claim():
            c = _connect(db)
            try:
                barrier.wait()
                JobRepository(c).claim_next("w1")
            finally:
                c.close()

        t1 = threading.Thread(target=cancel)
        t2 = threading.Thread(target=claim)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        conn = _connect(db)
        job_row = conn.execute(
            "SELECT status, cancel_requested FROM jobs WHERE id = 'job_1'"
        ).fetchone()
        lock = conn.execute(
            "SELECT active_job_id FROM projects WHERE id = 'prj_a'"
        ).fetchone()[0]
        conn.close()
        if job_row["status"] == "cancelled":
            assert lock is None
        elif job_row["status"] == "running":
            assert lock == "job_1"
        else:
            pytest.fail(f"unexpected status {job_row['status']!r}")


def test_finalize_terminal_job_is_idempotent_no_override(repo):
    """N3 回归：对已 cancelled 的 job finalize 不得覆盖终态。"""
    repo.create(make_job("job_1", status="cancelled", stage="finished"))
    done = repo.finalize("job_1", "succeeded")
    assert done.status == "cancelled"
    assert done.stage == "finished"


def test_concurrent_claim_next_single_winner(tmp_path):
    """N12 固化：双连接并发领取同一 queued job，只有一个赢家。"""
    import threading

    from courseware_core.storage.database import connect as _connect
    from courseware_core.storage.database import init_db as _init_db

    db = tmp_path / "race.db"
    seed = _connect(db)
    _init_db(seed)
    with seed:
        seed.execute(
            "INSERT INTO projects (id, course_json, current_version, corpus_revision,"
            " active_job_id, consent_to_cloud_processing, created_at, updated_at)"
            " VALUES ('prj_a', '{}', 0, 1, NULL, 1, ?, ?)",
            (T0, T0),
        )
    JobRepository(seed).create(make_job("job_race", created_at="2026-01-01T00:00:00+00:00"))
    seed.close()

    barrier = threading.Barrier(2)
    results: list = []

    def grab(wid):
        conn = _connect(db)
        try:
            barrier.wait()
            job = JobRepository(conn).claim_next(wid)
            results.append(job.id if job else None)
        finally:
            conn.close()

    t1 = threading.Thread(target=grab, args=("w1",))
    t2 = threading.Thread(target=grab, args=("w2",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert sorted(results, key=lambda x: (x is None, x or "")) == ["job_race", None]
