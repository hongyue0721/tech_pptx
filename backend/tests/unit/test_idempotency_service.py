from datetime import datetime, timedelta, timezone

import pytest

from courseware_core.errors import IdempotencyConflict
from courseware_core.services.idempotency_service import IdempotencyService
from courseware_core.storage.idempotency_repository import IdempotencyRepository

NOW = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)


def _clock(base: datetime):
    return lambda: base


@pytest.fixture()
def service(conn):
    return IdempotencyService(IdempotencyRepository(conn), clock=_clock(NOW))


def call_counting_produce(counter: list, result=(201, {"id": "p1"})):
    def _produce(binder):
        counter.append(1)
        return result

    return _produce


def test_first_call_executes_and_stores(service):
    counter: list = []
    res = service.execute("s|p|POST /x", "k1", "hash_a", call_counting_produce(counter))
    assert res.status == 201
    assert res.body == {"id": "p1"}
    assert counter == [1]


def test_same_key_same_hash_replays_without_reexecuting(service):
    counter: list = []
    first = service.execute("s|p|POST /x", "k1", "hash_a", call_counting_produce(counter))
    second = service.execute("s|p|POST /x", "k1", "hash_a", call_counting_produce(counter))
    assert first.status == second.status
    assert first.body == second.body
    assert counter == [1]


def test_same_key_different_hash_conflicts(service):
    service.execute("s|p|POST /x", "k1", "hash_a", call_counting_produce([]))
    counter: list = []
    with pytest.raises(IdempotencyConflict):
        service.execute("s|p|POST /x", "k1", "hash_b", call_counting_produce(counter))
    assert counter == []


def test_scope_isolates_keys(service):
    service.execute("s1|p|POST /x", "k1", "hash_a", call_counting_produce([]))
    counter: list = []
    service.execute("s2|p|POST /x", "k1", "hash_a", call_counting_produce(counter))
    assert counter == [1]


def test_expired_entry_is_replaced(service, conn):
    service.execute("s|p|POST /x", "k1", "hash_a", call_counting_produce([]))
    old = (NOW - timedelta(hours=25)).isoformat()
    with conn:
        conn.execute(
            "UPDATE idempotency_keys SET created_at = ? WHERE idem_key = 'k1'", (old,)
        )
    counter: list = []
    res = service.execute(
        "s|p|POST /x", "k1", "hash_a", call_counting_produce(counter, (201, {"id": "p2"}))
    )
    assert res.body == {"id": "p2"}
    assert counter == [1]


def test_produce_failure_is_not_recorded(service):
    def _boom(binder):
        raise RuntimeError("downstream failed")

    with pytest.raises(RuntimeError):
        service.execute("s|p|POST /x", "k1", "hash_a", _boom)
    counter: list = []
    service.execute("s|p|POST /x", "k1", "hash_a", call_counting_produce(counter))
    assert counter == [1]


def test_response_body_roundtrips_exact(service):
    body = {"id": "p1", "course": {"topic": "STM32 中断", "goals": ["a", "b"]}}
    res = service.execute("s|p|POST /x", "k1", "hash_a", lambda binder: (201, body))
    replay = service.execute("s|p|POST /x", "k1", "hash_a", lambda binder: (500, {}))
    assert replay.body == res.body == body


def test_fresh_placeholder_conflicts_as_in_flight(service, conn):
    from courseware_core.storage.idempotency_repository import IdempotencyRepository

    IdempotencyRepository(conn).try_reserve(
        "s|p|POST /x", "k9", "hash_a", NOW.isoformat()
    )
    counter: list = []
    with pytest.raises(IdempotencyConflict):
        service.execute("s|p|POST /x", "k9", "hash_a", call_counting_produce(counter))
    assert counter == []


def test_stale_placeholder_is_reclaimed(service, conn):
    """N5 回归：进程崩溃残留的占位行超过在飞窗口后必须可被同键请求接管重执行。"""
    from courseware_core.storage.idempotency_repository import IdempotencyRepository

    stale = (NOW - timedelta(hours=2)).isoformat()
    IdempotencyRepository(conn).try_reserve("s|p|POST /x", "k9", "hash_a", stale)
    counter: list = []
    res = service.execute("s|p|POST /x", "k9", "hash_a", call_counting_produce(counter))
    assert res.status == 201
    assert counter == [1]


class SimulatedCrash(BaseException):
    """模拟"业务事务已提交、响应缓存未写"时进程被杀。"""


def test_bound_produce_crash_keeps_anchor_and_recovers_original_job(service, conn):
    # R00-D：业务事务已提交（锚点已写）、响应缓存未写时崩溃——占位不得删除
    # （删了会重执行产生第二个 job），崩溃请求如实上抛（业务已提交，无法
    # 承诺结果），同键重试凭锚点找回原 job。
    from courseware_core.storage.idempotency_repository import RESERVED_PLACEHOLDER

    counter: list = []

    def _produce(binder):
        counter.append(1)
        binder.bind("job_crash")  # 业务事务内锚定（此处模拟事务已提交）
        with conn:
            pass  # 提交锚点，等同业务事务 commit 后进程被杀
        raise SimulatedCrash("killed after business commit, before response cache")

    with pytest.raises(SimulatedCrash):
        service.execute("s|p|POST /x", "k7", "hash_a", _produce)
    row = conn.execute(
        "SELECT response_status, operation_ref FROM idempotency_keys"
        " WHERE scope = 's|p|POST /x' AND idem_key = 'k7'"
    ).fetchone()
    assert row is not None, "已锚定业务的占位行不得被删除"
    assert row["response_status"] == RESERVED_PLACEHOLDER
    assert row["operation_ref"] == "job_crash"

    res = service.execute("s|p|POST /x", "k7", "hash_a", call_counting_produce(counter))
    assert res.status == 202
    assert res.body == {"job_id": "job_crash"}
    assert counter == [1], "恢复路径不得重新执行 produce"


def test_placeholder_with_anchor_recovers_without_reexecuting(service, conn):
    # 跨进程恢复：占位行+锚点由上一进程留下（直接落库模拟重启后状态）。
    from courseware_core.storage.idempotency_repository import IdempotencyRepository

    IdempotencyRepository(conn).try_reserve("s|p|POST /x", "k8", "hash_a", NOW.isoformat())
    with conn:
        conn.execute(
            "UPDATE idempotency_keys SET operation_ref = 'job_prev'"
            " WHERE scope = 's|p|POST /x' AND idem_key = 'k8'"
        )
    counter: list = []
    res = service.execute("s|p|POST /x", "k8", "hash_a", call_counting_produce(counter))
    assert res.status == 202
    assert res.body == {"job_id": "job_prev"}
    assert counter == []


def test_anchor_conflicts_on_different_request_hash(service, conn):
    # 恢复通道不得成为换载荷重跑的口子：同键不同 hash 仍是 409。
    from courseware_core.storage.idempotency_repository import IdempotencyRepository

    IdempotencyRepository(conn).try_reserve("s|p|POST /x", "k8", "hash_a", NOW.isoformat())
    with conn:
        conn.execute(
            "UPDATE idempotency_keys SET operation_ref = 'job_prev'"
            " WHERE scope = 's|p|POST /x' AND idem_key = 'k8'"
        )
    with pytest.raises(IdempotencyConflict):
        service.execute("s|p|POST /x", "k8", "hash_b", call_counting_produce([]))


def test_anchored_placeholder_survives_inflight_window(service, conn):
    # R00-Review B1 回归：崩溃后客户端 >60s 才重试（在飞窗口已过）——带锚点
    # 的占位不得被回收删除，否则同键重试会二次落 job，违背 api.md 恢复承诺。
    from courseware_core.storage.idempotency_repository import IdempotencyRepository

    crashed_at = NOW - timedelta(seconds=120)
    IdempotencyRepository(conn).try_reserve("s|p|POST /x", "k8", "hash_a", crashed_at.isoformat())
    with conn:
        conn.execute(
            "UPDATE idempotency_keys SET operation_ref = 'job_prev'"
            " WHERE scope = 's|p|POST /x' AND idem_key = 'k8'"
        )
    counter: list = []
    res = service.execute("s|p|POST /x", "k8", "hash_a", call_counting_produce(counter))
    assert res.status == 202
    assert res.body == {"job_id": "job_prev"}
    assert counter == []


def test_anchored_placeholder_still_expires_after_24h(service, conn):
    # 锚点豁免只针对 60s 在飞窗口；24h 幂等窗口过后按既有契约回收（重执行合法）。
    from courseware_core.storage.idempotency_repository import IdempotencyRepository

    ancient = (NOW - timedelta(hours=25)).isoformat()
    IdempotencyRepository(conn).try_reserve("s|p|POST /x", "k8", "hash_a", ancient)
    with conn:
        conn.execute(
            "UPDATE idempotency_keys SET operation_ref = 'job_prev'"
            " WHERE scope = 's|p|POST /x' AND idem_key = 'k8'"
        )
    counter: list = []
    res = service.execute("s|p|POST /x", "k8", "hash_a", call_counting_produce(counter))
    assert res.status == 201
    assert counter == [1]
