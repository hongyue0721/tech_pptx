"""兼容导入面：装配实现已下沉 core（T13），本模块保持既有 import 路径不变。"""

from courseware_core.services.worker_handlers import (
    build_worker_handlers,
    resolve_materials_root,
)

__all__ = ["build_worker_handlers", "resolve_materials_root"]
