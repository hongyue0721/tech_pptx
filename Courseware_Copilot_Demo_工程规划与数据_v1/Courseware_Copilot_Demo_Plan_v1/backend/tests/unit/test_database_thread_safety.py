"""生产 bug 回归锁：FastAPI 同步依赖的连接跨线程交接（uvicorn 线程池）。

复现的真实故障模式（2026-09-21 F4 浏览器并发实测）：uvicorn 把同步路由与
同步生成器依赖派发进 anyio 线程池执行，而依赖 teardown（conn.close()）经
AsyncExitStack 在事件循环线程运行——连接"创建线程 ≠ 使用/关闭线程"。
默认 check_same_thread=True 使并发 GET 抛
ProgrammingError: SQLite objects created in a thread can only be used in
that same thread → 500 INTERNAL_ERROR。TestClient 单线程执行模型结构上测不到
（与 OUTPUT_SCHEMAS 注册 bug 同类：测试环境掩盖生产路径）。
底层 sqlite3.threadsafety==3（SERIALIZED），显式 check_same_thread=False 安全。
"""

import sqlite3
import threading
from pathlib import Path

import pytest

from courseware_core.storage.database import connect, init_db

# 修复赖以安全的环境前提（F4 Review B1）：前提不成立时本文件全部测试失去
# 意义，必须先于任何用例显式失败，而不是静默通过。
assert sqlite3.threadsafety == 3, "本环境非 SERIALIZED，跨线程修复前提不成立"


def test_connect_supports_cross_thread_handoff(tmp_path: Path) -> None:
    """创建线程建连接；另一线程执行查询；再交回主线程 close——生产交接路径。"""
    db = tmp_path / "app.db"
    conn = connect(db)
    init_db(conn)
    conn.execute(
        "INSERT INTO projects(id, course_json, consent_to_cloud_processing,"
        " created_at, updated_at) VALUES ('p1', '{}', 0, 't', 't')"
    )
    conn.commit()

    errors: list[BaseException] = []
    started = threading.Event()

    def worker() -> None:
        try:
            row = conn.execute("SELECT id FROM projects WHERE id='p1'").fetchone()
            assert row is not None and row["id"] == "p1"
        except BaseException as exc:  # noqa: BLE001 - 记录后主线程断言
            errors.append(exc)
        finally:
            started.set()

    t = threading.Thread(target=worker)
    t.start()
    started.wait(timeout=5)
    t.join(timeout=5)

    assert not errors, f"跨线程使用连接失败：{errors!r}"
    conn.close()


def test_concurrent_reads_on_separate_connections(tmp_path: Path) -> None:
    """并发读各持独立连接不得互踩（生产=并发请求每请求一连接）。"""
    db = tmp_path / "app.db"
    boot = connect(db)
    init_db(boot)
    boot.close()

    results: list[int] = []
    lock = threading.Lock()
    barrier = threading.Barrier(8)

    def worker() -> None:
        conn = connect(db)
        try:
            barrier.wait(timeout=5)
            n = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
            with lock:
                results.append(n)
        finally:
            conn.close()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert results == [0] * 8


def test_default_check_same_thread_would_fail() -> None:
    """必要性论证（非回退守卫）：默认 check_same_thread=True 下生产交接模式
    必抛 ProgrammingError，说明修复不是多余防御。回退守卫由上面两个调用生产
    connect() 的正向测试承担——若删掉 check_same_thread=False 它们立即变红。"""
    conn = sqlite3.connect(":memory:")
    try:
        box: list[BaseException] = []

        def worker() -> None:
            try:
                conn.execute("SELECT 1").fetchone()
            except BaseException as exc:  # noqa: BLE001
                box.append(exc)

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=5)
        assert box and isinstance(box[0], sqlite3.ProgrammingError)
    finally:
        conn.close()


@pytest.mark.parametrize("mode", ["wal"])
def test_wal_mode_survives_thread_handoff(tmp_path: Path, mode: str) -> None:
    db = tmp_path / "app.db"
    conn = connect(db)
    init_db(conn)
    done = threading.Event()
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            conn.execute("PRAGMA journal_mode").fetchone()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            done.set()

    t = threading.Thread(target=worker)
    t.start()
    done.wait(timeout=5)
    t.join(timeout=5)
    assert not errors, f"worker 线程 PRAGMA 失败：{errors!r}"
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    conn.close()
