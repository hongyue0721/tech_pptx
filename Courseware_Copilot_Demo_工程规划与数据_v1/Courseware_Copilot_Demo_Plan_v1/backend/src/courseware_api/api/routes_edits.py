"""T12 edits 路由：POST /projects/{id}/edits → 202 JobAccepted（异步受限编辑）。"""

from fastapi import APIRouter, Depends, Request, Response

from courseware_api.dependencies import get_edit_service, get_idempotency_service
from courseware_api.idempotency import execute_idempotent
from courseware_core.models import EditRequest, JobAccepted
from courseware_core.services.edit_service import EditService
from courseware_core.services.idempotency_service import IdempotencyService

router = APIRouter()


@router.post("/projects/{project_id}/edits", status_code=202, response_model=JobAccepted)
def create_edit(
    request: Request,
    project_id: str,
    body: EditRequest,
    service: EditService = Depends(get_edit_service),
    idem: IdempotencyService = Depends(get_idempotency_service),
) -> Response:
    def produce(binder) -> tuple[int, dict]:
        accepted = service.create_edit_job(
            project_id, body, request_id=getattr(request.state, "request_id", None),
            binder=binder,
        )
        return 202, accepted.model_dump(mode="json")

    return execute_idempotent(
        request,
        idem,
        "POST /projects/{project_id}/edits",
        project_id,
        body,
        produce,
    )
