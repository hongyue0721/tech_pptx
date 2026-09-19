import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from courseware_core.errors import IdempotencyConflict
from courseware_core.storage.idempotency_repository import (
    RESERVED_PLACEHOLDER,
    IdempotencyRecord,
    IdempotencyRepository,
)

TTL_SECONDS = 24 * 3600
# 占位行（produce 未完成）的在飞窗口：进程崩溃残留的占位超过该窗口即可被同键请求接管，
# 避免崩溃后 24h 死锁（review N5）。
INFLIGHT_TTL_SECONDS = 60


@dataclass(frozen=True)
class CachedResponse:
    status: int
    body: Optional[dict]


class IdempotencyService:
    """docs/07 §2：同键同请求重放首次响应；同键不同请求 409 IDEMPOTENCY_CONFLICT；24h 过期。

    并发安全用占位行（INSERT OR IGNORE）闭合：抢到占位者才执行 produce，
    失败时删除占位，避免"两个请求都 miss 后各执行一次"。
    """

    def __init__(self, repo: IdempotencyRepository, clock=None):
        self._repo = repo
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def execute(
        self,
        scope: str,
        key: str,
        request_hash: str,
        produce,
    ) -> CachedResponse:
        now = self._clock()
        existing = self._repo.find(scope, key)
        if existing is not None and self._stale(existing, now):
            self._repo.delete(scope, key)
            existing = None
        if existing is not None:
            return self._replay_or_conflict(existing, request_hash)
        if not self._repo.try_reserve(scope, key, request_hash, now.isoformat()):
            raced = self._repo.find(scope, key)
            if raced is None:
                raise IdempotencyConflict(
                    {"scope": scope, "reason": "concurrent request still in flight"}
                )
            return self._replay_or_conflict(raced, request_hash)
        try:
            status, body = produce()
        except BaseException:
            self._repo.delete(scope, key)
            raise
        self._repo.store_response(scope, key, status, json.dumps(body), now.isoformat())
        return CachedResponse(status, body)

    @staticmethod
    def _replay_or_conflict(existing: IdempotencyRecord, request_hash: str) -> CachedResponse:
        if existing.request_hash != request_hash:
            raise IdempotencyConflict({"scope": existing.scope, "key": existing.idem_key})
        if existing.response_status == RESERVED_PLACEHOLDER:
            raise IdempotencyConflict(
                {"scope": existing.scope, "reason": "request with this key is in flight"}
            )
        return CachedResponse(existing.response_status, json.loads(existing.response_body))

    @staticmethod
    def _stale(record: IdempotencyRecord, now: datetime) -> bool:
        """成品响应按 24h TTL 过期；占位行按更短的在飞窗口过期（N5）。"""
        created = datetime.fromisoformat(record.created_at)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = (now - created).total_seconds()
        if record.response_status == RESERVED_PLACEHOLDER:
            return age > INFLIGHT_TTL_SECONDS
        return age > TTL_SECONDS
