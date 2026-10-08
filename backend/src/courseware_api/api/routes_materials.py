import hashlib

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile

from courseware_api.dependencies import (
    get_idempotency_service,
    get_material_service,
)
from courseware_api.idempotency import execute_idempotent
from courseware_core.errors import DomainError
from courseware_core.models import MaterialList, MaterialUploadAccepted
from courseware_core.services.idempotency_service import IdempotencyService
from courseware_core.services.material_service import MaterialService

router = APIRouter()


def _fingerprint(route: str, filename: str, data: bytes) -> str:
    """长度前缀消除域分隔歧义（N11）：文件名/路由含换行也无法移位碰撞。"""
    file_sha = hashlib.sha256(data).hexdigest()
    parts = [route, filename, file_sha]
    joined = "".join(f"{len(p)}:{p}" for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


@router.post(
    "/projects/{project_id}/materials",
    status_code=202,
    response_model=MaterialUploadAccepted,
)
def upload_material(
    request: Request,
    project_id: str,
    file: UploadFile = File(...),
    service: MaterialService = Depends(get_material_service),
    idem: IdempotencyService = Depends(get_idempotency_service),
) -> Response:
    # 同步路由与同步 DB 依赖同线程执行（async 路由会让线程池创建的
    # SQLite 连接跨线程使用而报错）；大 body 拒绝仍走统一错误形状（N1）。
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit():
        max_bytes = request.app.state.material_limits.max_file_bytes
        # 预留 multipart 边界/头开销：按 2 倍文件上限预检 Content-Length。
        if int(declared) > max_bytes * 2:
            raise DomainError(
                "PAYLOAD_TOO_LARGE", "declared upload size exceeds limit"
            )
    data = file.file.read()
    filename = file.filename or "unnamed.pdf"
    fingerprint = _fingerprint(
        f"POST /projects/{project_id}/materials", filename, data
    )

    def produce(binder) -> tuple[int, dict]:
        accepted = service.upload(project_id=project_id, original_name=filename, data=data)
        return 202, accepted.model_dump(mode="json")

    return execute_idempotent(
        request,
        idem,
        "POST /projects/{project_id}/materials",
        project_id,
        None,
        produce,
        request_hash_override=fingerprint,
    )


@router.get("/projects/{project_id}/materials", response_model=MaterialList)
def list_materials(
    project_id: str,
    service: MaterialService = Depends(get_material_service),
) -> MaterialList:
    return service.list_materials(project_id)
