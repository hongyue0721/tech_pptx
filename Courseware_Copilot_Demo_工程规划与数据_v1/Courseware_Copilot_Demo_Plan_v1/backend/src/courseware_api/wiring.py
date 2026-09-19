"""HTTP 层与后台 worker 的装配：handler 在 worker 线程内使用独立 SQLite 连接。"""

from pathlib import Path

from courseware_core.errors import ValidationFailed
from courseware_core.jobs.worker import JobHandler
from courseware_core.models import Job, JobResultRef
from courseware_core.services.material_service import MaterialService
from courseware_core.storage.database import connect


def build_worker_handlers(
    db_path: Path, materials_root: Path
) -> dict[str, JobHandler]:
    """worker_handlers 注入 create_app；每个 handler 每次执行开短事务/独立连接。"""

    def parse_handler(job: Job) -> JobResultRef:
        conn = connect(db_path)
        try:
            service = MaterialService(conn, materials_root=materials_root)
            return service.handle_parse(job)
        finally:
            conn.close()

    return {"parse": parse_handler}


def resolve_materials_root(db_path: Path, override: Path | None) -> Path:
    root = override if override is not None else db_path.parent / "materials"
    if ".." in str(root):
        raise ValidationFailed("materials root must not contain '..'")
    return Path(root)


def cleanup_orphan_material_files(materials_root: Path, db_path: Path) -> int:
    """启动 GC（docs/04 §47、review N4）：删除无 DB 指针的原件与残留 tmp 文件。

    只清"无指针"文件——有指针文件被删会导致 ARTIFACT/parse 读取显式失败，
    不属于启动期能自行决定的清理范围。
    """
    if not materials_root.exists():
        return 0
    conn = connect(db_path)
    try:
        referenced = {
            row["id"] for row in conn.execute("SELECT id FROM materials").fetchall()
        }
    finally:
        conn.close()
    removed = 0
    for path in materials_root.rglob("*"):
        if not path.is_file():
            continue
        if ".tmp-" in path.name or path.stem not in referenced:
            path.unlink(missing_ok=True)
            removed += 1
    return removed
