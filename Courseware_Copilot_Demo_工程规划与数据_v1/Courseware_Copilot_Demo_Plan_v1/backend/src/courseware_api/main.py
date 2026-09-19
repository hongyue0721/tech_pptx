import logging
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from courseware_api.api.routes_health import router as health_router
from courseware_api.api.routes_jobs import router as jobs_router
from courseware_api.api.routes_materials import router as materials_router
from courseware_api.api.routes_plans import router as plans_router
from courseware_api.api.routes_projects import router as projects_router
from courseware_api.error_mapping import _error_payload, register_error_handlers
from courseware_api.wiring import cleanup_orphan_material_files, resolve_materials_root
from courseware_core.jobs.worker import JobHandler, JobWorker
from courseware_core.services.material_service import ProjectLimits
from courseware_core.storage.database import connect, init_db

API_PREFIX = "/api/v1"

logger = logging.getLogger("courseware_api")

_REQUEST_ID_RE = re.compile(r"^[\x21-\x7e]{1,128}$")


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get("X-Request-ID")
        if incoming and _REQUEST_ID_RE.match(incoming):
            request_id = incoming
        else:
            request_id = f"req_{secrets.token_hex(12)}"
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception as exc:
            # 500 路径也必须带统一错误形状与 X-Request-ID（review N3）。
            # 中间件在 ServerErrorMiddleware 内侧，异常在此收口；日志只记异常类型，
            # 不落完整堆栈（AGENTS.md §6 日志脱敏，review N13）。
            logger.error(
                "unhandled error type=%s request_id=%s", type(exc).__name__, request_id
            )
            response = JSONResponse(
                status_code=500,
                content=_error_payload(
                    "INTERNAL_ERROR", "internal server error", request_id, {}
                ),
            )
        response.headers["X-Request-ID"] = request_id
        return response


def create_app(
    db_path: Path,
    worker_handlers: Optional[dict[str, JobHandler]] = None,
    materials_root: Optional[Path] = None,
    materials_limits: Optional[ProjectLimits] = None,
) -> FastAPI:
    """worker_handlers 不为 None 时按 docs/07 §1 在 app 启动期创建单后台工作器；
    P0 测试与骨架运行默认不启用（None），业务 handler 按需注入（T05 提供 parse）。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    init_db(conn)
    conn.close()

    materials_dir = resolve_materials_root(db_path, materials_root)
    cleanup_orphan_material_files(materials_dir, db_path)

    worker = (
        JobWorker(db_path, worker_handlers) if worker_handlers is not None else None
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if worker is not None:
            worker.start()
        try:
            yield
        finally:
            if worker is not None:
                worker.stop()

    app = FastAPI(
        title="Courseware Copilot API", docs_url=None, redoc_url=None, lifespan=lifespan
    )
    app.state.db_path = db_path
    app.state.materials_root = materials_dir
    app.state.material_limits = materials_limits or ProjectLimits()
    app.state.worker = worker
    app.add_middleware(RequestIDMiddleware)
    register_error_handlers(app)
    app.include_router(health_router, prefix=API_PREFIX)
    app.include_router(projects_router, prefix=API_PREFIX)
    app.include_router(jobs_router, prefix=API_PREFIX)
    app.include_router(materials_router, prefix=API_PREFIX)
    app.include_router(plans_router, prefix=API_PREFIX)
    return app
