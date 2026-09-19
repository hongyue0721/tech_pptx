import sqlite3
from typing import Iterator

from fastapi import Depends, Request

from courseware_core.services.idempotency_service import IdempotencyService
from courseware_core.services.job_service import JobService
from courseware_core.services.material_service import MaterialService
from courseware_core.services.plan_service import PlanService
from courseware_core.services.project_service import ProjectService
from courseware_core.storage.database import connect
from courseware_core.storage.idempotency_repository import IdempotencyRepository
from courseware_core.storage.job_repository import JobRepository
from courseware_core.storage.project_repository import ProjectRepository


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_project_service(conn: sqlite3.Connection = Depends(get_conn)) -> ProjectService:
    return ProjectService(ProjectRepository(conn))


def get_job_service(conn: sqlite3.Connection = Depends(get_conn)) -> JobService:
    return JobService(JobRepository(conn))


def get_idempotency_service(
    conn: sqlite3.Connection = Depends(get_conn),
) -> IdempotencyService:
    return IdempotencyService(IdempotencyRepository(conn))


def get_material_service(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> MaterialService:
    return MaterialService(
        conn,
        materials_root=request.app.state.materials_root,
        limits=request.app.state.material_limits,
    )


def get_plan_service(conn: sqlite3.Connection = Depends(get_conn)) -> PlanService:
    # 路由层只做受理/读取/确认，不调模型——provider 在 worker handler 注入。
    return PlanService(conn)
