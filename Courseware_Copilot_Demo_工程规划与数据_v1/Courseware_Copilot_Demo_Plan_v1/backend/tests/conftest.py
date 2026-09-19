import pytest

from courseware_core.storage.database import connect, init_db

T0 = "2026-09-19T00:00:00+00:00"


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    init_db(c)
    yield c
    c.close()


VALID_COURSE_JSON = (
    '{"topic": "STM32 中断", "audience": "大二",'
    ' "duration_minutes": 45, "goals": ["理解 NVIC"], "target_slides": 8}'
)


@pytest.fixture()
def insert_project(conn):
    def _insert(
        project_id: str,
        *,
        current_version: int = 0,
        corpus_revision: int = 0,
        active_job_id: str | None = None,
    ) -> None:
        with conn:
            conn.execute(
                "INSERT INTO projects (id, course_json, current_version,"
                " corpus_revision, active_job_id, consent_to_cloud_processing,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                (
                    project_id,
                    VALID_COURSE_JSON,
                    current_version,
                    corpus_revision,
                    active_job_id,
                    T0,
                    T0,
                ),
            )

    return _insert


@pytest.fixture()
def project_columns(conn):
    def _columns(project_id: str) -> dict:
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        return dict(row) if row else {}

    return _columns
