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


# 锚定恢复响应的状态码：bind 仅用于 202 受理型操作（JobAccepted），
# 恢复响应必须与首次受理同形同码（api.md 幂等节）。
_RECOVERED_ACCEPT_STATUS = 202


class OperationBinder:
    """produce 期间的业务锚点写入器（R00-D）。

    bind(ref) 必须发生在业务资源写入的同一 SQLite 事务内（由业务仓储的
    on_committed 回调通道保证），使"业务已提交 ⇔ 锚点存在"原子成立。
    """

    def __init__(self, repo: IdempotencyRepository, scope: str, key: str):
        self._repo = repo
        self._scope = scope
        self._key = key
        self.ref: Optional[str] = None

    def bind(self, ref: str) -> None:
        self._repo.bind_operation(self._scope, self._key, ref)
        self.ref = ref


class IdempotencyService:
    """docs/07 §2：同键同请求重放首次响应；同键不同请求 409 IDEMPOTENCY_CONFLICT；24h 过期。

    并发安全用占位行（INSERT OR IGNORE）闭合：抢到占位者才执行 produce，
    失败时删除占位，避免"两个请求都 miss 后各执行一次"。

    R00-D 锚点恢复：produce(binder) 可把业务资源 id 锚定到占位行；业务已提交
    但响应缓存未写时崩溃/抛错，占位行因锚点保留，同键重试凭锚点找回原业务
    结果（202 JobAccepted），既不 409 死等也不重执行产生第二个资源。
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
        binder = OperationBinder(self._repo, scope, key)
        try:
            status, body = produce(binder)
        except BaseException:
            # 以 DB 为事实源裁决：业务事务回滚时锚点一并回滚（find 看不到），
            # 删占位、原样抛出（等同从未执行）。锚点已在=业务已提交但响应
            # 无法承诺——保留占位行、如实上抛；同键重试凭锚点找回原业务结果。
            current = self._repo.find(scope, key)
            if current is None or current.operation_ref is None:
                self._repo.delete(scope, key)
            raise
        self._repo.store_response(scope, key, status, json.dumps(body), now.isoformat())
        return CachedResponse(status, body)

    @staticmethod
    def _replay_or_conflict(existing: IdempotencyRecord, request_hash: str) -> CachedResponse:
        if existing.request_hash != request_hash:
            raise IdempotencyConflict({"scope": existing.scope, "key": existing.idem_key})
        if existing.response_status == RESERVED_PLACEHOLDER:
            if existing.operation_ref is not None:
                # 上一进程"业务已提交、响应未缓存"的遗留：找回原 job（R00-D）。
                return CachedResponse(
                    _RECOVERED_ACCEPT_STATUS, {"job_id": existing.operation_ref}
                )
            raise IdempotencyConflict(
                {"scope": existing.scope, "reason": "request with this key is in flight"}
            )
        return CachedResponse(existing.response_status, json.loads(existing.response_body))

    @staticmethod
    def _stale(record: IdempotencyRecord, now: datetime) -> bool:
        """成品响应按 24h TTL 过期；占位行按更短的在飞窗口过期（N5）。

        R00-Review B1：已锚定业务（operation_ref 非空）的占位=业务已提交，
        不得按 60s 在飞窗口回收——否则晚到的同键重试会重执行、二次落 job，
        违背 api.md 恢复承诺；与成品响应同按 24h 窗口管理。
        """
        created = datetime.fromisoformat(record.created_at)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = (now - created).total_seconds()
        if record.response_status == RESERVED_PLACEHOLDER:
            if record.operation_ref is not None:
                return age > TTL_SECONDS
            return age > INFLIGHT_TTL_SECONDS
        return age > TTL_SECONDS
