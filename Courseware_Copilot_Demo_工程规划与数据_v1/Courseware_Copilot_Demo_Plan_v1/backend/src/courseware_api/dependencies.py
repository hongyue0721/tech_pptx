import sqlite3
from typing import Iterator

from fastapi import Depends, Request

from courseware_core.services.project_service import ProjectService
from courseware_core.storage.database import connect
from courseware_core.storage.project_repository import ProjectRepository


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_project_service(conn: sqlite3.Connection = Depends(get_conn)) -> ProjectService:
    return ProjectService(ProjectRepository(conn))
