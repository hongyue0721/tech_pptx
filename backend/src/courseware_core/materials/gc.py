"""启动期孤儿文件 GC（docs/04 §47、T05 review N4、R00-B 锁序收口）。

时序契约（硬约束）：只在 JobWorker 取得数据目录独占锁之后、执行线程启动之前
运行一次；运行期绝不周期执行。原因：上传路径"文件先落盘、DB 指针后提交"存在
活动窗口，任何锁外/运行期的扫描都可能把在途上传文件误当孤儿删除。
只清"无指针"文件——有指针文件被删会导致 parse/ARTIFACT 读取显式失败，
不属于启动期能自行决定的清理范围。
"""

from pathlib import Path

from courseware_core.storage.database import connect


def cleanup_orphan_material_files(materials_root: Path, db_path: Path) -> int:
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
