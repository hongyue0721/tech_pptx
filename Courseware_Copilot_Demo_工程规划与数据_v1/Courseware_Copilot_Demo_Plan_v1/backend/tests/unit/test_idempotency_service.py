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
    def _produce():
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
    def _boom():
        raise RuntimeError("downstream failed")

    with pytest.raises(RuntimeError):
        service.execute("s|p|POST /x", "k1", "hash_a", _boom)
    counter: list = []
    service.execute("s|p|POST /x", "k1", "hash_a", call_counting_produce(counter))
    assert counter == [1]


def test_response_body_roundtrips_exact(service):
    body = {"id": "p1", "course": {"topic": "STM32 中断", "goals": ["a", "b"]}}
    res = service.execute("s|p|POST /x", "k1", "hash_a", lambda: (201, body))
    replay = service.execute("s|p|POST /x", "k1", "hash_a", lambda: (500, {}))
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
