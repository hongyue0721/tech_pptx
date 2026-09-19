"""plans 表仓库：受理（占锁建plan job同事务）与 LessonPlan 读写。"""

import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from courseware_core.errors import ProjectBusy, ProjectNotFound
from courseware_core.models import LessonPlan


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PlanRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create_with_job(
        self,
        project_id: str,
        *,
        job_id: str,
        corpus_revision: int,
        request_id: Optional[str] = None,
    ) -> None:
        """CAS占项目写锁 + INSERT plan job 同一事务（与 T05 create_with_job 同语义）。

        锁被占→ProjectBusy；项目不存在→ProjectNotFound。corpus_revision 由
        service 校验等于项目当前值后才走到这里。
        """
        now = _now_iso()
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
                " created_at, updated_at)"
                " VALUES (?, ?, 'plan', 'queued', 'queued', 0, ?, ?, NULL, NULL, 0, ?, ?, ?)",
                (
                    job_id,
                    project_id,
                    proj["current_version"],
                    corpus_revision,
                    request_id,
                    now,
                    now,
                ),
            )

    def insert(self, plan: LessonPlan) -> None:
        now = _now_iso()
        with self._conn:
            self._conn.execute(
                "INSERT INTO plans (id, project_id, corpus_revision, status,"
                " plan_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    plan.id,
                    plan.project_id,
                    plan.corpus_revision,
                    plan.status,
                    plan.model_dump_json(),
                    now,
                    now,
                ),
            )

    def get(self, plan_id: str) -> Optional[LessonPlan]:
        row = self._conn.execute(
            "SELECT plan_json FROM plans WHERE id = ?", (plan_id,)
        ).fetchone()
        if row is None:
            return None
        return LessonPlan.model_validate_json(row["plan_json"])

    def update(self, plan: LessonPlan) -> None:
        """状态迁移更新（confirm）。plan_json 为真源，status 列冗余同步。"""
        now = _now_iso()
        with self._conn:
            cur = self._conn.execute(
                "UPDATE plans SET status = ?, plan_json = ?, updated_at = ?"
                " WHERE id = ?",
                (plan.status, plan.model_dump_json(), now, plan.id),
            )
            if cur.rowcount == 0:
                raise ProjectNotFound({"plan_id": plan.id})


def new_plan_id() -> str:
    return f"plan_{secrets.token_hex(16)}"
