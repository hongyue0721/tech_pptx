import hashlib
import json
from typing import Callable, Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from courseware_core.errors import ValidationFailed
from courseware_core.models import ContractModel
from courseware_core.services.idempotency_service import (
    CachedResponse,
    IdempotencyService,
    OperationBinder,
)
from courseware_core.storage.idempotency_repository import IdempotencyRepository

IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"


def require_idempotency_key(request: Request) -> str:
    value = request.headers.get(IDEMPOTENCY_KEY_HEADER)
    if value is None or not (1 <= len(value) <= 128):
        raise ValidationFailed(
            "mutating operations require Idempotency-Key (1-128 chars)",
            {"header": IDEMPOTENCY_KEY_HEADER},
        )
    return value


def get_session_id(request: Request) -> str:
    """幂等 scope 的会话分量（docs/07 §2）。P0 未启用认证时为 local，
    单用户前提下所有创建请求共享 POST /projects 键空间可接受（review N7）；
    接入 demoBasic 后由认证层写入 request.state.session_id 即按会话隔离，无需改这里。"""
    return getattr(request.state, "session_id", "local")


def build_scope(request: Request, route: str, project_ref: str) -> str:
    return f"{get_session_id(request)}|{project_ref}|{route}"


def compute_request_hash(route: str, body: Optional[ContractModel]) -> str:
    payload = (
        json.dumps(
            body.model_dump(mode="json"),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if body is not None
        else ""
    )
    return hashlib.sha256(f"{route}\n{payload}".encode("utf-8")).hexdigest()


def execute_idempotent(
    request: Request,
    service: IdempotencyService,
    route: str,
    project_ref: str,
    body: Optional[ContractModel],
    produce: Callable[[OperationBinder], tuple[int, Optional[dict]]],
    request_hash_override: Optional[str] = None,
) -> Response:
    key = require_idempotency_key(request)
    scope = build_scope(request, route, project_ref)
    request_hash = request_hash_override or compute_request_hash(route, body)
    result: CachedResponse = service.execute(scope, key, request_hash, produce)
    if result.body is None:
        return Response(status_code=result.status)
    return JSONResponse(status_code=result.status, content=result.body)
