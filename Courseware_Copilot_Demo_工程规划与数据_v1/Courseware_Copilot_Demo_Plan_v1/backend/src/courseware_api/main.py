import re
import secrets
from pathlib import Path

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from courseware_api.api.routes_health import router as health_router
from courseware_api.api.routes_projects import router as projects_router
from courseware_api.error_mapping import register_error_handlers
from courseware_core.storage.database import connect, init_db

API_PREFIX = "/api/v1"

_REQUEST_ID_RE = re.compile(r"^[\x21-\x7e]{1,128}$")


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get("X-Request-ID")
        if incoming and _REQUEST_ID_RE.match(incoming):
            request_id = incoming
        else:
            request_id = f"req_{secrets.token_hex(12)}"
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


def create_app(db_path: Path) -> FastAPI:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    init_db(conn)
    conn.close()

    app = FastAPI(title="Courseware Copilot API", docs_url=None, redoc_url=None)
    app.state.db_path = db_path
    app.add_middleware(RequestIDMiddleware)
    register_error_handlers(app)
    app.include_router(health_router, prefix=API_PREFIX)
    app.include_router(projects_router, prefix=API_PREFIX)
    return app
