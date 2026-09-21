"""T12 restores 路由：POST /projects/{id}/restores → 201 DeckVersion。"""

from fastapi import APIRouter, Depends, Request, Response

from courseware_api.dependencies import get_idempotency_service, get_restore_service
from courseware_api.idempotency import execute_idempotent
from courseware_core.models import DeckVersion, RestoreRequest
from courseware_core.services.idempotency_service import IdempotencyService
from courseware_core.services.restore_service import RestoreService

router = APIRouter()


@router.post("/projects/{project_id}/restores", status_code=201, response_model=DeckVersion)
def restore_version(
    request: Request,
    project_id: str,
    body: RestoreRequest,
    service: RestoreService = Depends(get_restore_service),
    idem: IdempotencyService = Depends(get_idempotency_service),
) -> Response:
    def produce(binder) -> tuple[int, dict]:
        return 201, service.restore(project_id, body).model_dump(mode="json")

    return execute_idempotent(
        request,
        idem,
        "POST /projects/{project_id}/restores",
        project_id,
        body,
        produce,
    )
