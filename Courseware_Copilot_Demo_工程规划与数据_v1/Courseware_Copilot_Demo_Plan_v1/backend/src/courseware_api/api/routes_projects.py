from fastapi import APIRouter, Depends, Request, Response

from courseware_api.dependencies import (
    get_idempotency_service,
    get_project_service,
)
from courseware_api.idempotency import execute_idempotent
from courseware_core.models import (
    ConfirmDeleteRequest,
    CreateProjectRequest,
    Project,
)
from courseware_core.services.idempotency_service import IdempotencyService
from courseware_core.services.project_service import ProjectService

router = APIRouter()


@router.post("/projects", status_code=201, response_model=Project)
def create_project(
    request: Request,
    body: CreateProjectRequest,
    service: ProjectService = Depends(get_project_service),
    idem: IdempotencyService = Depends(get_idempotency_service),
) -> Response:
    def produce() -> tuple[int, dict]:
        return 201, service.create_project(body).model_dump(mode="json")

    return execute_idempotent(request, idem, "POST /projects", "-", body, produce)


@router.get("/projects/{project_id}", response_model=Project)
def get_project(
    project_id: str,
    service: ProjectService = Depends(get_project_service),
) -> Project:
    return service.get_project(project_id)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(
    request: Request,
    project_id: str,
    body: ConfirmDeleteRequest,
    service: ProjectService = Depends(get_project_service),
    idem: IdempotencyService = Depends(get_idempotency_service),
) -> Response:
    def produce() -> tuple[int, None]:
        service.delete_project(project_id, body)
        return 204, None

    return execute_idempotent(
        request, idem, "DELETE /projects/{project_id}", project_id, body, produce
    )
