"""T09 changes 路由：受理生成 / 候选读取（commit 在循环③加入本模块）。"""

from fastapi import APIRouter, Depends, Request, Response

from courseware_api.dependencies import get_generate_service, get_idempotency_service
from courseware_api.idempotency import execute_idempotent
from courseware_core.models import (
    CandidateChange,
    CommitRequest,
    DeckVersion,
    GenerateRequest,
    JobAccepted,
)
from courseware_core.services.generate_service import GenerateService
from courseware_core.services.idempotency_service import IdempotencyService

router = APIRouter()


@router.post("/projects/{project_id}/generations", status_code=202, response_model=JobAccepted)
def create_generation(
    request: Request,
    project_id: str,
    body: GenerateRequest,
    service: GenerateService = Depends(get_generate_service),
    idem: IdempotencyService = Depends(get_idempotency_service),
) -> Response:
    def produce(binder) -> tuple[int, dict]:
        accepted = service.create_generate_job(
            project_id, body, request_id=getattr(request.state, "request_id", None),
            binder=binder,
        )
        return 202, accepted.model_dump(mode="json")

    return execute_idempotent(
        request,
        idem,
        "POST /projects/{project_id}/generations",
        project_id,
        body,
        produce,
    )


@router.get("/projects/{project_id}/changes/{change_id}", response_model=CandidateChange)
def get_change(
    project_id: str,
    change_id: str,
    service: GenerateService = Depends(get_generate_service),
) -> CandidateChange:
    return service.get_change(project_id, change_id)


@router.post(
    "/projects/{project_id}/changes/{change_id}/commit",
    status_code=201,
    response_model=DeckVersion,
)
def commit_change(
    request: Request,
    project_id: str,
    change_id: str,
    body: CommitRequest,
    service: GenerateService = Depends(get_generate_service),
    idem: IdempotencyService = Depends(get_idempotency_service),
) -> Response:
    def produce(binder) -> tuple[int, dict]:
        version = service.commit_change(project_id, change_id, body)
        return 201, version.model_dump(mode="json")

    # scope 含 change_id：不同候选的提交不得共用键空间。
    return execute_idempotent(
        request,
        idem,
        "POST /projects/{project_id}/changes/{change_id}/commit",
        f"{project_id}|{change_id}",
        body,
        produce,
    )
