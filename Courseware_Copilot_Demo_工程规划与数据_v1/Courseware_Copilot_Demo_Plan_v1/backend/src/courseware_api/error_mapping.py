import secrets

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from courseware_core.errors import DomainError
from courseware_core.models import ErrorDetail, ErrorResponse

DOMAIN_ERROR_STATUS = {
    "UNAUTHORIZED": 401,
    "PROJECT_NOT_FOUND": 404,
    "DECK_NOT_FOUND": 404,
    "JOB_NOT_FOUND": 404,
    "ARTIFACT_NOT_FOUND": 404,
    "PLAN_NOT_FOUND": 404,
    "PAYLOAD_TOO_LARGE": 413,
    "PAGE_LIMIT_EXCEEDED": 413,
    "EXTRACTION_LIMIT_EXCEEDED": 413,
    "UNSUPPORTED_FILE": 422,
    "PDF_ENCRYPTED": 422,
    "PDF_TEXT_UNAVAILABLE": 422,
    "EVIDENCE_INVALID": 422,
    "VALIDATION_ERROR": 422,
    "EDIT_UNSUPPORTED": 422,
    "INSUFFICIENT_EVIDENCE": 422,
    "BUDGET_EXCEEDED": 422,
    "IDEMPOTENCY_CONFLICT": 409,
    "VERSION_CONFLICT": 409,
    "CORPUS_CHANGED": 409,
    "PROJECT_BUSY": 409,
    "PLAN_NOT_CONFIRMED": 409,
    # 云推理入口的告知门禁：确认后须重新创建项目（P0 无项目更新路由）。
    "CONSENT_REQUIRED": 409,
    # JobCancelled 只在 worker 内的 LLM 调用路径抛出并由 worker 收口为 job 终态
    # （api.md 定性"job终态"）；此映射是同步路径缺省兜底，当前无同步抛出点。
    "CANCELLED": 409,
    "WORKER_ALREADY_RUNNING": 409,
    # LLM 错误码组按 api.md §错误码表：502=修配置，503=临时不可用受预算重试。
    # 异步执行中同类错误走 GET Job 的 error 字段体现，不经 HTTP 状态。
    "MODEL_AUTH_ERROR": 502,
    "MODEL_PROTOCOL_ERROR": 502,
    "MODEL_OUTPUT_INVALID": 502,
    "MODEL_RATE_LIMIT": 503,
    "MODEL_TIMEOUT": 503,
    "MODEL_UNAVAILABLE": 503,
    "ARTIFACT_INTEGRITY": 500,
}

# Starlette层HTTPException（未注册路由404、方法405等）也必须输出统一错误形状（api.md通用约定）。
HTTP_EXCEPTION_CODES = {
    401: "UNAUTHORIZED",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "PAYLOAD_TOO_LARGE",
}


def _request_id(request: Request) -> str:
    """middleware正常时取注入值；异常路径兜底生成，保证非空（ErrorResponse minLength=1）。"""
    rid = getattr(request.state, "request_id", None)
    return rid or f"req_{secrets.token_hex(12)}"


def _error_payload(code: str, message: str, request_id: str, details: dict) -> dict:
    """经Pydantic模型构造，保证序列化形状与契约一致（review N1：不绕过校验手拼dict）。"""
    return ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message[:2000],
            request_id=request_id,
            details=details,
        )
    ).model_dump(mode="json")


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        status = DOMAIN_ERROR_STATUS.get(exc.code, 500)
        return JSONResponse(
            status_code=status,
            content=_error_payload(exc.code, exc.message, _request_id(request), exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        fields = [
            {"location": list(err.get("loc", [])), "message": err.get("msg", "")}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_error_payload(
                "VALIDATION_ERROR",
                "request validation failed",
                _request_id(request),
                {"fields": fields},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        if exc.status_code >= 500:
            code = "INTERNAL_ERROR"
        else:
            code = HTTP_EXCEPTION_CODES.get(exc.status_code, "VALIDATION_ERROR")
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(code, str(exc.detail), _request_id(request), {}),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content=_error_payload(
                "INTERNAL_ERROR", "internal server error", _request_id(request), {}
            ),
        )
