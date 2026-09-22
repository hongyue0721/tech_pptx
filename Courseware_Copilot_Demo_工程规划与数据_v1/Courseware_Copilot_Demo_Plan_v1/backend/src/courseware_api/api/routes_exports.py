"""T10 exports 路由：POST /projects/{id}/exports → 202 JobAccepted；
GET /projects/{id}/artifacts/{artifact_id}/download → 二进制交付。"""

from fastapi import APIRouter, Depends, Request, Response

from courseware_api.dependencies import (
    get_artifact_store,
    get_export_service,
    get_idempotency_service,
)
from courseware_api.idempotency import execute_idempotent
from courseware_core.errors import ArtifactNotFound
from courseware_core.models import JobAccepted
from courseware_core.models.export import ExportRequest
from courseware_core.services.export_service import ExportService, artifact_filename
from courseware_core.services.idempotency_service import IdempotencyService
from courseware_core.storage.artifact_store import ArtifactStore

router = APIRouter()


@router.post("/projects/{project_id}/exports", status_code=202, response_model=JobAccepted)
def create_export(
    request: Request,
    project_id: str,
    body: ExportRequest,
    service: ExportService = Depends(get_export_service),
    idem: IdempotencyService = Depends(get_idempotency_service),
) -> Response:
    def produce(binder) -> tuple[int, dict]:
        job = service.create_export_job(
            project_id, body, request_id=getattr(request.state, "request_id", None)
        )
        return 202, JobAccepted(job_id=job.id).model_dump(mode="json")

    return execute_idempotent(
        request,
        idem,
        "POST /projects/{project_id}/exports",
        project_id,
        body,
        produce,
    )


@router.get("/projects/{project_id}/artifacts/{artifact_id}/download")
def download_artifact(
    request: Request,
    project_id: str,
    artifact_id: str,
    store: ArtifactStore = Depends(get_artifact_store),
) -> Response:
    record = store.get(artifact_id)
    # 跨项目按不存在处理，不泄露存在性（与 changes/jobs 同口径）。
    if record is None or record.project_id != project_id:
        raise ArtifactNotFound({"artifact_id": artifact_id})
    data = store.read_verified(artifact_id)
    return Response(
        content=data,
        media_type=record.mime,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact_filename(record)}"',
            "X-Artifact-Sha256": record.sha256,
        },
    )
