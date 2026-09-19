import fcntl
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from courseware_core.errors import DomainError, WorkerAlreadyRunning
from courseware_core.models import ErrorDetail, ErrorResponse, Job, JobResultRef
from courseware_core.storage.database import connect
from courseware_core.storage.job_repository import JobRepository

JobHandler = Callable[[Job], Optional[JobResultRef]]


class JobCancelled(Exception):
    """handler 协作式取消：worker 捕获后把 job 置为 cancelled。"""


def _error_response(code: str, message: str) -> ErrorResponse:
    return ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message[:2000],
            request_id=f"worker_{secrets.token_hex(8)}",
            details={},
        )
    )


class JobWorker:
    """FastAPI 进程内单后台工作器（docs/07 §1）。

    - 单实例：flock 独占锁文件，第二个 worker 直接 WorkerAlreadyRunning；
    - 启动恢复：上一进程遗留的 running job 标 interrupted，绝不自动重放（可能已产生费用）；
    - 领取：SQLite 单语句 CAS，claimed 后在 worker 线程执行注册的 handler；
    - 线程内使用独立 SQLite 连接（连接不跨线程）。
    """

    def __init__(
        self,
        db_path: Path,
        handlers: dict[str, JobHandler],
        *,
        poll_interval: float = 0.2,
        worker_id: Optional[str] = None,
        lock_path: Optional[Path] = None,
    ):
        self._db_path = Path(db_path)
        self._handlers = dict(handlers)
        self._poll_interval = poll_interval
        self._worker_id = worker_id or f"worker_{secrets.token_hex(6)}"
        self._lock_path = lock_path or Path(str(self._db_path) + ".worker.lock")
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock_fd: Optional[int] = None

    @property
    def worker_id(self) -> str:
        return self._worker_id

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("worker already started")
        self._acquire_singleton_lock()
        try:
            self._recover_on_startup()
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run, name=f"job-worker-{self._worker_id}", daemon=True
            )
            self._thread.start()
        except BaseException:
            self._release_singleton_lock()
            self._thread = None
            raise

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        self._release_singleton_lock()

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _recover_on_startup(self) -> None:
        conn = connect(self._db_path)
        try:
            JobRepository(conn).mark_interrupted_on_startup()
        finally:
            conn.close()

    def _run(self) -> None:
        conn = connect(self._db_path)
        repo = JobRepository(conn)
        try:
            while not self._stop_event.is_set():
                job = repo.claim_next(self._worker_id)
                if job is None:
                    self._stop_event.wait(self._poll_interval)
                    continue
                self._execute(repo, job)
        finally:
            conn.close()

    def _execute(self, repo: JobRepository, job: Job) -> None:
        if job.cancel_requested:
            repo.finalize(job.id, "cancelled")
            return
        handler = self._handlers.get(job.kind)
        if handler is None:
            repo.finalize(
                job.id,
                "failed",
                error=_error_response("INTERNAL_ERROR", f"no handler registered for {job.kind}"),
            )
            return
        try:
            result_ref = handler(job)
        except JobCancelled:
            repo.finalize(job.id, "cancelled")
        except DomainError as exc:
            repo.finalize(
                job.id, "failed", error=_error_response(exc.code, exc.message)
            )
        except Exception:
            repo.finalize(
                job.id,
                "failed",
                error=_error_response("INTERNAL_ERROR", "job execution failed"),
            )
        else:
            repo.finalize(job.id, "succeeded", result_ref=result_ref)

    def _acquire_singleton_lock(self) -> None:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            raise WorkerAlreadyRunning({"lock_path": str(self._lock_path)}) from exc
        os.ftruncate(fd, 0)
        os.write(fd, f"{self._worker_id} {datetime.now(timezone.utc).isoformat()}\n".encode())
        self._lock_fd = fd

    def _release_singleton_lock(self) -> None:
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(self._lock_fd)
                self._lock_fd = None
