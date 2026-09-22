"""开发启动入口：装配 parse/plan/generate/edit/export handlers + 唯一 worker，仅绑回环。

create_app(worker_handlers=None) 是测试工厂——直接当业务服务跑会"受理 job
但永远无人执行"（假可用）。本模块是开发/演示的真实装配点：
- 三个业务 handler 全部注册，worker 单实例锁语义照旧；
- 只绑定 127.0.0.1，不暴露公网（AGENTS §6）；
- 模型凭据仍走 APP_LLM_* 环境惰性构造，不落盘。
"""

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI

from courseware_api.main import create_app
from courseware_api.wiring import build_worker_handlers

DEV_HOST = "127.0.0.1"


def build_dev_app(db_path: Optional[Path] = None) -> FastAPI:
    db = Path(db_path or os.environ.get("APP_DB_PATH", "data/app.db"))
    db.parent.mkdir(parents=True, exist_ok=True)
    materials = Path(
        os.environ.get("APP_MATERIALS_DIR", str(db.parent / "materials"))
    )
    artifacts = Path(
        os.environ.get("APP_ARTIFACTS_DIR", str(db.parent / "artifacts"))
    )
    handlers = build_worker_handlers(db, materials, artifacts_root=artifacts)
    return create_app(
        db, worker_handlers=handlers, materials_root=materials, artifacts_root=artifacts
    )


def serve(db_path: Optional[Path] = None) -> None:
    import uvicorn

    app = build_dev_app(db_path)
    uvicorn.run(app, host=DEV_HOST, port=int(os.environ.get("APP_PORT", "8000")))


if __name__ == "__main__":
    serve()
