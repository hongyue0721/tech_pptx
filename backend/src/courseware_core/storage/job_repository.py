import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from courseware_core.errors import JobNotFound
from courseware_core.models import ErrorResponse, Job, JobResultRef

# blocked（资料不足，INSUFFICIENT_EVIDENCE）是"本次执行终止"的稳定终态：
# 释放项目锁、不自动重放；教师补材料/收窄目标后重新受理新 job（api.md:59）。
_TERMINAL_STATUSES = frozenset(
    {"succeeded", "failed", "cancelled", "interrupted", "blocked"}
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobRepository:
    """jobs 表持久化。领取用单语句 CAS（RETURNING），终态与项目锁释放在同一事务。"""

    # docs/06：项目任务总预算 600 秒（受理即落 deadline，执行侧据此收口）。
    DEFAULT_DEADLINE_SECONDS = 600

    def __init__(
        self, conn: sqlite3.Connection, job_deadline_seconds: int = DEFAULT_DEADLINE_SECONDS
    ):
        self._conn = conn
        self._job_deadline_seconds = job_deadline_seconds

    def create(self, job: Job, request_id: Optional[str] = None) -> None:
        deadline_at = (job.created_at + timedelta(seconds=self._job_deadline_seconds)).isoformat()
        with self._conn:
            self._conn.execute(
                "INSERT INTO jobs (id, project_id, kind, status, stage, cancel_requested,"
                " base_version, corpus_revision, result_ref, error, llm_calls, request_id,"
                " deadline_at, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job.id,
                    job.project_id,
                    job.kind,
                    job.status,
                    job.stage,
                    int(job.cancel_requested),
                    job.base_version,
                    job.corpus_revision,
                    job.result_ref.model_dump_json() if job.result_ref else None,
                    job.error.model_dump_json() if job.error else None,
                    job.llm_calls,
                    request_id,
                    deadline_at,
                    job.created_at.isoformat(),
                    job.updated_at.isoformat(),
                ),
            )

    def get(self, job_id: str) -> Optional[Job]:
        row = self._conn.execute(
            "SELECT * FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return self._row_to_job(row) if row is not None else None

    def claim_next(self, worker_id: str, now: Optional[str] = None) -> Optional[Job]:
        """单语句原子领取 queued→running；并发下只有一个 worker 能拿到。

        写 kind（parse/plan/generate/edit）必须已持有项目锁才可领取（review N8），
        防止"占锁+建 job"不变式被破坏时同项目并发两个写任务；export 是只读快照可排队。
        """
        now = now or _now_iso()
        with self._conn:
            row = self._conn.execute(
                "UPDATE jobs SET status = 'running', worker_id = ?, claimed_at = ?,"
                " updated_at = ?"
                " WHERE id = ("
                "   SELECT j.id FROM jobs j"
                "   JOIN projects p ON p.id = j.project_id"
                "   WHERE j.status = 'queued'"
                "     AND (j.kind = 'export' OR p.active_job_id = j.id)"
                "   ORDER BY j.created_at, j.id LIMIT 1)"
                " RETURNING id",
                (worker_id, now, now),
            ).fetchone()
        if row is None:
            return None
        return self.get(row["id"])

    def mark_interrupted_on_startup(self, now: Optional[str] = None) -> list[str]:
        """上一个进程遗留的 running job 标 interrupted（不重放），并释放其项目锁。"""
        now = now or _now_iso()
        with self._conn:
            ids = [
                r["id"]
                for r in self._conn.execute(
                    "SELECT id FROM jobs WHERE status = 'running'"
                ).fetchall()
            ]
            if ids:
                self._conn.execute(
                    "UPDATE jobs SET status = 'interrupted', updated_at = ?"
                    " WHERE status = 'running'",
                    (now,),
                )
                for job_id in ids:
                    self._conn.execute(
                        "UPDATE projects SET active_job_id = NULL, updated_at = ?"
                        " WHERE active_job_id = ?",
                        (now, job_id),
                    )
        return ids

    def request_cancel(self, job_id: str, now: Optional[str] = None) -> Optional[Job]:
        """queued→cancelled（释放锁）；running→置 cancel_requested 由 worker 边界终止；终态原样返回。

        全 CAS：读状态只用于最终返回，状态迁移由 UPDATE 守卫决定，
        避免"读到 queued 后被 worker 领取、再被取消路径强改 cancelled"的 TOCTOU（review B1）。
        """
        now = now or _now_iso()
        with self._conn:
            cur = self._conn.execute(
                "UPDATE jobs SET status = 'cancelled', stage = 'finished',"
                " cancel_requested = 1, updated_at = ? WHERE id = ? AND status = 'queued'",
                (now, job_id),
            )
            if cur.rowcount > 0:
                self._conn.execute(
                    "UPDATE projects SET active_job_id = NULL, updated_at = ?"
                    " WHERE active_job_id = ?",
                    (now, job_id),
                )
            else:
                self._conn.execute(
                    "UPDATE jobs SET cancel_requested = 1, updated_at = ?"
                    " WHERE id = ? AND status = 'running'",
                    (now, job_id),
                )
        return self.get(job_id)

    def finalize(
        self,
        job_id: str,
        status: str,
        *,
        stage: str = "finished",
        result_ref: Optional[JobResultRef] = None,
        error: Optional[ErrorResponse] = None,
        now: Optional[str] = None,
    ) -> Job:
        """写终态并释放该 job 持有的项目锁（同一事务）。

        带 running 守卫（review N3）：终态不可被二次 finalize 覆盖，重复调用幂等返回当前行。
        """
        if status not in _TERMINAL_STATUSES:
            raise ValueError(f"finalize requires terminal status, got {status!r}")
        now = now or _now_iso()
        with self._conn:
            cur = self._conn.execute(
                "UPDATE jobs SET status = ?, stage = ?, result_ref = ?, error = ?,"
                " updated_at = ? WHERE id = ? AND status = 'running'",
                (
                    status,
                    stage,
                    result_ref.model_dump_json() if result_ref else None,
                    error.model_dump_json() if error else None,
                    now,
                    job_id,
                ),
            )
            if cur.rowcount > 0:
                self._conn.execute(
                    "UPDATE projects SET active_job_id = NULL, updated_at = ?"
                    " WHERE active_job_id = ?",
                    (now, job_id),
                )
        result = self.get(job_id)
        if result is None:
            raise JobNotFound({"job_id": job_id})
        return result

    def get_execution_state(self, job_id: str) -> Optional[dict]:
        """发布结果前的轻量复核通道：内部执行列（worker_id）不在 Job 契约模型里。"""
        row = self._conn.execute(
            "SELECT status, cancel_requested, worker_id FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def get_deadline_remaining(self, job_id: str) -> Optional[float]:
        """任务剩余时间预算（秒）。

        None=无 deadline（v1 遗留行）；负值=总预算已耗尽，执行侧必须在任何
        昂贵动作（模型调用/切块入库）之前收口。
        """
        row = self._conn.execute(
            "SELECT deadline_at FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if row is None or row["deadline_at"] is None:
            return None
        deadline = datetime.fromisoformat(row["deadline_at"])
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        return (deadline - datetime.now(timezone.utc)).total_seconds()

    def get_params(self, job_id: str) -> dict:
        """受理参数内部列（T09：generate 的 plan_id/base_version），无则空 dict。"""
        row = self._conn.execute(
            "SELECT params_json FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if row is None or not row["params_json"]:
            return {}
        return json.loads(row["params_json"])

    def accumulate_llm_calls(self, job_id: str, attempts: int) -> None:
        # jobs.llm_calls 列 CHECK 0-24（docs/06 预算）；封顶不报错，如实累计。
        with self._conn:
            self._conn.execute(
                "UPDATE jobs SET llm_calls = MIN(24, llm_calls + ?) WHERE id = ?",
                (attempts, job_id),
            )

    def set_stage(self, job_id: str, stage: str, now: Optional[str] = None) -> Job:
        """进行中任务的 stage 上报。

        R00-Review N2：带 running 守卫——stale worker（任务已被外部收口为
        终态/interrupted）的迟到上报不得把终态行写回进行中；静默 no-op。
        """
        now = now or _now_iso()
        with self._conn:
            cur = self._conn.execute(
                "UPDATE jobs SET stage = ?, updated_at = ?"
                " WHERE id = ? AND status = 'running'",
                (stage, now, job_id),
            )
            if cur.rowcount == 0:
                if self.get(job_id) is None:
                    raise JobNotFound({"job_id": job_id})
        result = self.get(job_id)
        assert result is not None
        return result

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            project_id=row["project_id"],
            kind=row["kind"],
            status=row["status"],
            stage=row["stage"],
            cancel_requested=bool(row["cancel_requested"]),
            base_version=row["base_version"],
            corpus_revision=row["corpus_revision"],
            result_ref=(
                JobResultRef.model_validate_json(row["result_ref"])
                if row["result_ref"]
                else None
            ),
            error=(
                ErrorResponse.model_validate_json(row["error"]) if row["error"] else None
            ),
            llm_calls=row["llm_calls"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
