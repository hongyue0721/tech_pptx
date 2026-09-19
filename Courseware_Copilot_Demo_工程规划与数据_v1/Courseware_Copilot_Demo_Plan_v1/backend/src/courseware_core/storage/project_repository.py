import sqlite3
from typing import Optional

from courseware_core.models import CourseBrief, Project


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
