"""changes 表仓库（T09）：CandidateChange 整对象持久化与状态 CAS。

stale 是读路径计算（base_version 落后 current_version / corpus 前进），
与 plans 同语义——不写库，避免与并发提交互相制造脏状态；committed 由
commit 路径的 CAS 单点写入（WHERE status='ready'），并发输家不得覆盖。
create_generate_job 与 T05/T08 同语义：占项目写锁 + 插 generate job +
幂等锚点回调在同一事务，崩溃不留指向不存在 job 的锁。
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from courseware_core.errors import ProjectBusy, ProjectNotFound
from courseware_core.models import CandidateChange
from courseware_core.storage.job_repository import JobRepository


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ChangeRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create_generate_job(
        self,
        project_id: str,
        *,
        job_id: str,
        corpus_revision: int,
        params_json: str,
        request_id: Optional[str] = None,
        on_committed: Optional[Callable[[sqlite3.Connection], None]] = None,
    ) -> None:
        now = _now_iso()
        deadline_at = (
            datetime.now(timezone.utc)
            + timedelta(seconds=JobRepository.DEFAULT_DEADLINE_SECONDS)
        ).isoformat(timespec="seconds")
        with self._conn:
            cur = self._conn.execute(
                "UPDATE projects SET active_job_id = ?, updated_at = ?"
                " WHERE id = ? AND active_job_id IS NULL",
                (job_id, now, project_id),
            )
            if cur.rowcount == 0:
                row = self._conn.execute(
                    "SELECT active_job_id FROM projects WHERE id = ?", (project_id,)
                ).fetchone()
                if row is None:
                    raise ProjectNotFound({"project_id": project_id})
                raise ProjectBusy({"active_job_id": row["active_job_id"]})
            proj = self._conn.execute(
                "SELECT current_version FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            self._conn.execute(
                "INSERT INTO jobs (id, project_id, kind, status, stage, cancel_requested,"
                " base_version, corpus_revision, result_ref, error, llm_calls, request_id,"
                " deadline_at, params_json, created_at, updated_at)"
                " VALUES (?, ?, 'generate', 'queued', 'queued', 0, ?, ?, NULL, NULL,"
                " 0, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    project_id,
                    proj["current_version"],
                    corpus_revision,
                    request_id,
                    deadline_at,
                    params_json,
                    now,
                    now,
                ),
            )
            if on_committed is not None:
                on_committed(self._conn)

    def create(self, change: CandidateChange) -> None:
        now = _now_iso()
        with self._conn:
            self._conn.execute(
                "INSERT INTO changes (id, project_id, base_version, corpus_revision,"
                " status, kind, change_json, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    change.id,
                    change.project_id,
                    change.base_version,
                    change.corpus_revision,
                    change.status,
                    change.kind,
                    change.model_dump_json(),
                    now,
                    now,
                ),
            )

    def get(self, change_id: str) -> Optional[CandidateChange]:
        row = self._conn.execute(
            "SELECT change_json FROM changes WHERE id = ?", (change_id,)
        ).fetchone()
        return CandidateChange.model_validate_json(row["change_json"]) if row else None

    def mark_committed(self, change_id: str) -> bool:
        """ready→committed 的 CAS（自管事务，独立调用场景用）。"""
        with self._conn:
            return self.mark_committed_tx(self._conn, change_id, _now_iso())

    def mark_committed_tx(self, conn: sqlite3.Connection, change_id: str, now: str) -> bool:
        """在调用方事务内迁移状态（T09-Review N4：SQL 单一实现，不自开事务）。

        status 列与 change_json 内嵌 status 同一语句改写（json_set），
        否则 get() 从 JSON 读回的对外形状落后于列——双源漂移。
        返回 False=状态已被他人迁移（并发 commit 输家）。
        """
        cur = conn.execute(
            "UPDATE changes SET status = 'committed',"
            " change_json = json_set(change_json, '$.status', 'committed'),"
            " updated_at = ?"
            " WHERE id = ? AND status = 'ready'",
            (now, change_id),
        )
        return cur.rowcount > 0
