import secrets
from datetime import datetime, timezone

from courseware_core.errors import ProjectBusy, ProjectNotFound
from courseware_core.models import ConfirmDeleteRequest, CreateProjectRequest, Project
from courseware_core.storage.project_repository import ProjectRepository


def _generate_id() -> str:
    return secrets.token_hex(16)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectService:
    def __init__(self, repo: ProjectRepository):
        self._repo = repo

    def create_project(self, request: CreateProjectRequest) -> Project:
        now = _utc_now_iso()
        project = Project(
            id=_generate_id(),
            course=request.course,
            current_version=0,
            corpus_revision=0,
            active_job_id=None,
            consent_to_cloud_processing=request.consent_to_cloud_processing,
            created_at=now,
            updated_at=now,
        )
        self._repo.insert(project)
        return project

    def get_project(self, project_id: str) -> Project:
        project = self._repo.get(project_id)
        if project is None:
            raise ProjectNotFound()
        return project

    def delete_project(self, project_id: str, request: ConfirmDeleteRequest) -> None:
        project = self._repo.get(project_id)
        if project is None:
            raise ProjectNotFound()
        if project.active_job_id is not None:
            raise ProjectBusy({"active_job_id": project.active_job_id})
        self._repo.delete(project_id)
