import sqlite3
import threading
import time
from pathlib import Path

import pytest

from courseware_core.errors import DomainError, WorkerAlreadyRunning
from courseware_core.models import Job, JobResultRef
from courseware_core.jobs.worker import JobWorker
from courseware_core.storage.database import connect, init_db
from courseware_core.storage.job_repository import JobRepository

T0 = "2026-09-19T00:00:00+00:00"


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    p = tmp_path / "worker.db"
    conn = connect(p)
    init_db(conn)
    conn.close()
    return p


def seed_job(db_path: Path, job_id: str, status: str = "queued", project_id: str = "prj_w"):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO projects (id, course_json, current_version,"
                " corpus_revision, active_job_id, consent_to_cloud_processing,"
                " created_at, updated_at) VALUES (?, '{}', 0, 1, NULL, 1, ?, ?)",
                (project_id, T0, T0),
            )
        JobRepository(conn).create(
            Job(
                id=job_id,
                project_id=project_id,
                kind="parse",
                status=status,
                stage="queued",
                cancel_requested=False,
                base_version=0,
                corpus_revision=1,
                created_at=T0,
                updated_at=T0,
            )
        )
    finally:
        conn.close()


def wait_until(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def job_status(db_path: Path, job_id: str) -> str:
    conn = connect(db_path)
    try:
        row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return row["status"] if row else None
    finally:
        conn.close()


def test_startup_recovery_marks_running_interrupted_without_replay(db_path):
    calls: list = []
    seed_job(db_path, "job_old", status="running")
    worker = JobWorker(db_path, handlers={"parse": lambda j: calls.append(j)}, poll_interval=0.02)
    worker.start()
    try:
        assert job_status(db_path, "job_old") == "interrupted"
        time.sleep(0.15)
        assert calls == []
    finally:
        worker.stop()


def test_worker_executes_queued_job_to_succeeded(db_path):
    ref = JobResultRef(type="material", id="mat_1")
    seed_job(db_path, "job_q", status="queued")
    conn = connect(db_path)
    with conn:
        conn.execute("UPDATE projects SET active_job_id = 'job_q' WHERE id = 'prj_w'")
    conn.close()
    worker = JobWorker(db_path, handlers={"parse": lambda j: ref}, poll_interval=0.02)
    worker.start()
    try:
        assert wait_until(lambda: job_status(db_path, "job_q") == "succeeded")
    finally:
        worker.stop()
    conn = connect(db_path)
    try:
        row = conn.execute("SELECT result_ref, projects.active_job_id AS lock FROM jobs, projects WHERE jobs.id = 'job_q' AND projects.id = 'prj_w'").fetchone()
        assert row["result_ref"] is not None
        assert row["lock"] is None
    finally:
        conn.close()


def test_worker_marks_handler_domain_error_as_failed(db_path):
    def _boom(job: Job):
        raise DomainError("VALIDATION_ERROR", "材料不可用")

    seed_job(db_path, "job_f", status="queued")
    worker = JobWorker(db_path, handlers={"parse": _boom}, poll_interval=0.02)
    worker.start()
    try:
        assert wait_until(lambda: job_status(db_path, "job_f") == "failed")
    finally:
        worker.stop()


def test_worker_marks_unexpected_exception_as_failed(db_path):
    def _boom(job: Job):
        raise RuntimeError("kaboom")

    seed_job(db_path, "job_u", status="queued")
    worker = JobWorker(db_path, handlers={"parse": _boom}, poll_interval=0.02)
    worker.start()
    try:
        assert wait_until(lambda: job_status(db_path, "job_u") == "failed")
    finally:
        worker.stop()


def test_single_worker_enforced_by_lock(db_path):
    w1 = JobWorker(db_path, handlers={}, poll_interval=0.05)
    w2 = JobWorker(db_path, handlers={}, poll_interval=0.05)
    w1.start()
    try:
        with pytest.raises(WorkerAlreadyRunning):
            w2.start()
    finally:
        w1.stop()
    w2.start()
    w2.stop()


def test_stop_terminates_thread(db_path):
    worker = JobWorker(db_path, handlers={}, poll_interval=0.02)
    worker.start()
    worker.stop()
    assert worker.is_alive() is False


def test_app_lifespan_runs_single_worker(tmp_path):
    from fastapi.testclient import TestClient

    from courseware_api.main import create_app

    db = tmp_path / "app" / "app.db"
    ref = JobResultRef(type="material", id="mat_life")
    app = create_app(db, worker_handlers={"parse": lambda j: ref})
    seed_job(db, "job_life", status="queued")
    with TestClient(app) as c:
        assert c.get("/api/v1/health").status_code == 200
        assert wait_until(lambda: job_status(db, "job_life") == "succeeded")
    assert job_status(db, "job_life") == "succeeded"
