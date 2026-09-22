"""HTTP 层与后台 worker 的装配：handler 在 worker 线程内使用独立 SQLite 连接。"""

from pathlib import Path
from typing import Optional

from courseware_core.errors import ModelProtocolError, ValidationFailed
from courseware_core.jobs.worker import JobHandler
from courseware_core.llm.adapter import ChatCompletionsAdapter
from courseware_core.llm.config import LLMConfig
from courseware_core.models import Job, JobResultRef
from courseware_core.services.export_service import ExportService
from courseware_core.services.generate_service import GenerateService
from courseware_core.services.edit_service import EditService
from courseware_core.services.material_service import MaterialService
from courseware_core.services.plan_service import PlanService
from courseware_core.storage.database import connect


def build_worker_handlers(
    db_path: Path,
    materials_root: Path,
    plan_provider: Optional[object] = None,
    artifacts_root: Optional[Path] = None,
) -> dict[str, JobHandler]:
    """worker_handlers 注入 create_app；每个 handler 每次执行开短事务/独立连接。

    plan_provider=None 时按 APP_LLM_* 环境变量惰性构造真实 adapter
    （凭据只从环境读取，不落盘）；测试注入 Fake provider 走同一代码路径。
    """
    cached_provider = plan_provider
    cached_model_id: Optional[str] = None

    def resolve_provider():
        nonlocal cached_provider, cached_model_id
        if cached_provider is None:
            try:
                config = LLMConfig.from_env()
            except ValueError as exc:
                raise ModelProtocolError(
                    f"APP_LLM_* configuration missing or invalid: {exc}"
                ) from exc
            cached_provider = ChatCompletionsAdapter(config)
            cached_model_id = config.model
        return cached_provider

    def parse_handler(job: Job) -> JobResultRef:
        conn = connect(db_path)
        try:
            service = MaterialService(conn, materials_root=materials_root)
            return service.handle_parse(job)
        finally:
            conn.close()

    def plan_handler(job: Job) -> JobResultRef:
        conn = connect(db_path)
        try:
            service = PlanService(conn, provider=resolve_provider())
            return service.handle_plan(job)
        finally:
            conn.close()

    def generate_handler(job: Job) -> JobResultRef:
        conn = connect(db_path)
        try:
            # model_id 在 resolve_provider 后才有值；注入 Fake 时保持 None=unknown。
            provider = resolve_provider()
            service = GenerateService(conn, provider=provider, model_id=cached_model_id)
            return service.handle_generate(job)
        finally:
            conn.close()

    def edit_handler(job: Job) -> JobResultRef:
        conn = connect(db_path)
        try:
            # 确定性 reorder 不外发模型：provider 只经 factory 惰性解析（loop④），
            # 无 APP_LLM_* 环境下确定性路径也必须可执行。N-5：provider 与
            # model_id 必须同源解析（与 generate_handler 口径一致），
            # 预注入 Fake 时 resolve_provider 原样返回、model_id=None=unknown。
            service = EditService(
                conn,
                provider_factory=lambda: (resolve_provider(), cached_model_id),
            )
            return service.handle_edit(job)
        finally:
            conn.close()

    def export_handler(job: Job) -> JobResultRef:
        conn = connect(db_path)
        try:
            # 纯渲染零模型零外发：不经 provider，无凭据环境也必须可执行。
            root = artifacts_root if artifacts_root is not None else db_path.parent / "artifacts"
            service = ExportService(conn, artifacts_root=root)
            return JobResultRef(type="artifact", id=service.handle_export(job.id))
        finally:
            conn.close()

    return {
        "parse": parse_handler,
        "plan": plan_handler,
        "generate": generate_handler,
        "edit": edit_handler,
        "export": export_handler,
    }


def resolve_materials_root(db_path: Path, override: Path | None) -> Path:
    # 注意：启动孤儿 GC 不在本层——已移至 courseware_core.materials.gc，
    # 由 JobWorker 在取得数据目录独占锁后执行（R00-B 锁序收口）。
    root = override if override is not None else db_path.parent / "materials"
    if ".." in str(root):
        raise ValidationFailed("materials root must not contain '..'")
    return Path(root)
