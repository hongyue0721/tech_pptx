import pytest

from courseware_core.errors import ProjectBusy, ProjectNotFound
from courseware_core.storage.project_repository import ProjectRepository


@pytest.fixture()
def repo(conn, insert_project):
    insert_project("prj_a")
    insert_project("prj_b")
    return ProjectRepository(conn)


def test_acquire_sets_active_job(repo, project_columns):
    repo.acquire_write_lock("prj_a", "job_1")
    assert project_columns("prj_a")["active_job_id"] == "job_1"


def test_acquire_twice_raises_busy(repo):
    repo.acquire_write_lock("prj_a", "job_1")
    with pytest.raises(ProjectBusy) as exc:
        repo.acquire_write_lock("prj_a", "job_2")
    assert exc.value.details.get("active_job_id") == "job_1"


def test_lock_is_per_project(repo, conn, project_columns):
    repo.acquire_write_lock("prj_a", "job_1")
    repo.acquire_write_lock("prj_b", "job_2")
    assert project_columns("prj_a")["active_job_id"] == "job_1"
    assert project_columns("prj_b")["active_job_id"] == "job_2"


def test_acquire_missing_project_raises_not_found(repo):
    with pytest.raises(ProjectNotFound):
        repo.acquire_write_lock("nope", "job_1")


def test_release_by_holder_clears(repo, project_columns):
    repo.acquire_write_lock("prj_a", "job_1")
    repo.release_write_lock("prj_a", "job_1")
    assert project_columns("prj_a")["active_job_id"] is None


def test_release_by_wrong_holder_is_noop(repo, project_columns):
    repo.acquire_write_lock("prj_a", "job_1")
    repo.release_write_lock("prj_a", "job_other")
    assert project_columns("prj_a")["active_job_id"] == "job_1"
