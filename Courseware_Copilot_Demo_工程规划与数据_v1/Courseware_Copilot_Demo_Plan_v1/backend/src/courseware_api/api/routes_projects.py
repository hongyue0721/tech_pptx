from fastapi import APIRouter, Depends, Request, Response

from courseware_api.dependencies import get_project_service
from courseware_core.errors import ValidationFailed
from courseware_core.models import (
    ConfirmDeleteRequest,
    CreateProjectRequest,
    Project,
)
from courseware_core.services.project_service import ProjectService

router = APIRouter()

IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"


def require_idempotency_key(request: Request) -> str:
    value = request.headers.get(IDEMPOTENCY_KEY_HEADER)
    if value is None or not (1 <= len(value) <= 128):
        raise ValidationFailed(
            "mutating operations require Idempotency-Key (1-128 chars)",
            {"header": IDEMPOTENCY_KEY_HEADER},
        )
    return value


@router.post("/projects", status_code=201, response_model=Project)
def create_project(
    body: CreateProjectRequest,
    service: ProjectService = Depends(get_project_service),
    _idem: str = Depends(require_idempotency_key),
) -> Project:
    return service.create_project(body)


@router.get("/projects/{project_id}", response_model=Project)
def get_project(
    project_id: str,
    service: ProjectService = Depends(get_project_service),
) -> Project:
    return service.get_project(project_id)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(
    project_id: str,
    body: ConfirmDeleteRequest,
    service: ProjectService = Depends(get_project_service),
    _idem: str = Depends(require_idempotency_key),
) -> Response:
    service.delete_project(project_id, body)
    return Response(status_code=204)
