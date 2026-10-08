"""CLI 运行时：data-dir 布局、数据目录独占锁、内联 job 执行与终态等待。

锁与 JobWorker 同源（worker_lock_path）：同一 data-dir 上 CLI 与 Web worker
互斥——误指向运行中服务的数据目录时立即 WORKER_ALREADY_RUNNING，
不存在"绕过服务边界改同一 SQLite"的窗口（docs/10 §5）。
"""

import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

from courseware_core.errors import WorkerAlreadyRunning
from courseware_core.jobs.worker import JobWorker, worker_lock_path
from courseware_core.models import Job
from courseware_core.services.worker_handlers import build_worker_handlers
from courseware_core.storage.database import connect, init_db
from courseware_core.storage.job_repository import JobRepository

TERMINAL_STATUSES = frozenset(
    {"succeeded", "failed", "blocked", "cancelled", "interrupted"}
)

# 等待上限 = 业务 deadline（模型 600s / 渲染 120s）+ 收尾余量；
# 超时=执行者失能（worker 线程死亡类内部故障），按 INTERNAL 暴露而非谎报。
WAIT_GRACE_SECONDS = 30.0


class DataDir:
    """Skill 独立演示数据目录：app.db + materials/ + artifacts/（与 dev 装配同布局）。"""

    def __init__(self, path: Path):
        self.root = Path(path)
        self.db_path = self.root / "app.db"
        self.materials_root = self.root / "materials"
        self.artifacts_root = self.root / "artifacts"

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.materials_root.mkdir(parents=True, exist_ok=True)
        self.artifacts_root.mkdir(parents=True, exist_ok=True)
        conn = connect(self.db_path)
        try:
            init_db(conn)
        finally:
            conn.close()

    def open(self) -> sqlite3.Connection:
        return connect(self.db_path)


class DataDirLock:
    """非 job 命令的数据目录独占锁（与 worker 同一把 flock，互斥成立）。"""

    def __init__(self, data: DataDir):
        self._path = worker_lock_path(data.db_path)
        self._fd: Optional[int] = None

    def __enter__(self) -> "DataDirLock":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            raise WorkerAlreadyRunning({"lock_path": str(self._path)}) from exc
        self._fd = fd
        return self

    def __exit__(self, *exc_info) -> None:
        if self._fd is not None:
            import fcntl

            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None


def probe_lock(data: DataDir) -> str:
    """doctor 用：available / held（不创建目录、不做任何写入）。"""
    lock = worker_lock_path(data.db_path)
    if not lock.exists():
        return "available"
    fd = os.open(lock, os.O_RDWR)
    try:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return "available"
    except OSError:
        return "held"
    finally:
        os.close(fd)


def recover_interrupted(conn: sqlite3.Connection) -> None:
    """与 worker 启动恢复同语义：遗留 running→interrupted（不重放），
    释放项目写锁，避免上一次进程崩溃把后续同步命令永久卡在 PROJECT_BUSY。
    job 命令路径由 JobWorker.start() 自带恢复，不重复调用。
    """
    JobRepository(conn).mark_interrupted_on_startup()


class InlineJobRunner:
    """job 受理命令的执行者：临时启动一个真正的 JobWorker（锁/恢复/GC/CAS
    全复用 worker 语义），等待本命令的 job 到达终态后停止。

    不复制一套"CLI 专用执行器"平行语义：worker 会顺带领取 data-dir 中
    其他 queued job（与 Web 启动后领取积压同语义，如实文档化）。
    """

    def __init__(self, data: DataDir, provider: Optional[object] = None):
        self._data = data
        self._provider = provider
        self._worker: Optional[JobWorker] = None

    def __enter__(self) -> "InlineJobRunner":
        handlers = build_worker_handlers(
            self._data.db_path,
            self._data.materials_root,
            plan_provider=self._provider,
            artifacts_root=self._data.artifacts_root,
        )
        self._worker = JobWorker(
            self._data.db_path, handlers, materials_root=self._data.materials_root
        )
        self._worker.start()
        return self

    def __exit__(self, *exc_info) -> None:
        if self._worker is not None:
            try:
                self._worker.stop()
            except RuntimeError:
                # handler 卡死时 stop 拒绝释锁（R00-B）。with 块已有原始异常
                # 则以原始异常为主因上抛（review N5：不让锁告警盖掉根因线索）；
                # 无原始异常时如实上抛 stop 失败。锁随进程退出释放，不谎报。
                if exc_info[0] is None:
                    raise
            finally:
                self._worker = None

    def wait(self, conn: sqlite3.Connection, job_id: str) -> Job:
        repo = JobRepository(conn)
        deadline = time.monotonic() + WAIT_GRACE_SECONDS + _job_budget_seconds(repo, job_id)
        while True:
            job = repo.get(job_id)
            if job is None:
                raise RuntimeError(f"job {job_id} vanished while waiting")
            if job.status in TERMINAL_STATUSES:
                return job
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"job {job_id} still {job.status} beyond deadline + grace"
                )
            time.sleep(0.02)


def _job_budget_seconds(repo: JobRepository, job_id: str) -> float:
    remaining = repo.get_deadline_remaining(job_id)
    if remaining is None:
        return WAIT_GRACE_SECONDS
    return max(remaining, 0.0) + 5.0
