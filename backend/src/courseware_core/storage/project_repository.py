import sqlite3
from datetime import datetime, timezone
from typing import Optional

from courseware_core.errors import ProjectBusy, ProjectNotFound
from courseware_core.models import CourseBrief, Project


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def insert(self, project: Project) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO projects (id, course_json, current_version, corpus_revision,"
                " active_job_id, consent_to_cloud_processing, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    project.id,
                    project.course.model_dump_json(),
                    project.current_version,
                    project.corpus_revision,
                    project.active_job_id,
                    int(project.consent_to_cloud_processing),
                    project.created_at.isoformat(),
                    project.updated_at.isoformat(),
                ),
            )

    def get(self, project_id: str) -> Optional[Project]:
        row = self._conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_project(row)

    def delete(self, project_id: str) -> bool:
        with self._conn:
            cur = self._conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        return cur.rowcount > 0

    def acquire_write_lock(self, project_id: str, job_id: str) -> None:
        """同项目同一时刻最多一个写任务（docs/07 §3）：CAS 占用 active_job_id。"""
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

    def release_write_lock(self, project_id: str, job_id: str) -> None:
        """只释放自己持有的锁；holder 不匹配时为空操作，不误解放他人的锁。"""
        now = _now_iso()
        with self._conn:
            self._conn.execute(
                "UPDATE projects SET active_job_id = NULL, updated_at = ?"
                " WHERE id = ? AND active_job_id = ?",
                (now, project_id, job_id),
            )

    @staticmethod
    def _row_to_project(row: sqlite3.Row) -> Project:
        return Project(
            id=row["id"],
            course=CourseBrief.model_validate_json(row["course_json"]),
            current_version=row["current_version"],
            corpus_revision=row["corpus_revision"],
            active_job_id=row["active_job_id"],
            consent_to_cloud_processing=bool(row["consent_to_cloud_processing"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
