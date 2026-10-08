import sqlite3
from pathlib import Path

import pytest

from courseware_core.errors import ProjectBusy, ProjectNotFound
from courseware_core.models import ConfirmDeleteRequest, CreateProjectRequest
from courseware_core.services.project_service import ProjectService
from courseware_core.storage.database import connect, init_db
from courseware_core.storage.project_repository import ProjectRepository


@pytest.fixture()
def service(tmp_path: Path) -> tuple[ProjectService, sqlite3.Connection]:
    conn = connect(tmp_path / "test.db")
    init_db(conn)
    return ProjectService(ProjectRepository(conn)), conn


def make_request() -> CreateProjectRequest:
    return CreateProjectRequest(
        course={
            "topic": "STM32 中断",
            "audience": "大二",
            "duration_minutes": 45,
            "goals": ["理解 NVIC"],
            "target_slides": 8,
        },
        consent_to_cloud_processing=True,
    )


def test_create_then_get(service):
    svc, _ = service
    created = svc.create_project(make_request())
    fetched = svc.get_project(created.id)
    assert fetched == created
    assert created.current_version == 0
    assert created.id and created.id != "STM32 中断"


def test_ids_unique(service):
    svc, _ = service
    a = svc.create_project(make_request())
    b = svc.create_project(make_request())
    assert a.id != b.id


def test_get_missing_raises(service):
    svc, _ = service
    with pytest.raises(ProjectNotFound):
        svc.get_project("nope")


def test_delete_ok(service):
    svc, _ = service
    p = svc.create_project(make_request())
    svc.delete_project(p.id, ConfirmDeleteRequest(acknowledged=True))
    with pytest.raises(ProjectNotFound):
        svc.get_project(p.id)


def test_delete_with_active_job_raises_busy(service):
    svc, conn = service
    p = svc.create_project(make_request())
    with conn:
        conn.execute("UPDATE projects SET active_job_id = ? WHERE id = ?", ("job_1", p.id))
    with pytest.raises(ProjectBusy):
        svc.delete_project(p.id, ConfirmDeleteRequest(acknowledged=True))
