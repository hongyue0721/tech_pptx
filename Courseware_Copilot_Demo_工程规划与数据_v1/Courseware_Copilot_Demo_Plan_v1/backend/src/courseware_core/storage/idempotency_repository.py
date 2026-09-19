import sqlite3
from dataclasses import dataclass
from typing import Optional

RESERVED_PLACEHOLDER = -1


@dataclass(frozen=True)
class IdempotencyRecord:
    scope: str
    idem_key: str
    request_hash: str
    response_status: int
    response_body: str
    created_at: str


class IdempotencyRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def find(self, scope: str, key: str) -> Optional[IdempotencyRecord]:
        row = self._conn.execute(
            "SELECT * FROM idempotency_keys WHERE scope = ? AND idem_key = ?",
            (scope, key),
        ).fetchone()
        if row is None:
            return None
        return IdempotencyRecord(
            scope=row["scope"],
            idem_key=row["idem_key"],
            request_hash=row["request_hash"],
            response_status=row["response_status"],
            response_body=row["response_body"],
            created_at=row["created_at"],
        )

    def try_reserve(self, scope: str, key: str, request_hash: str, created_at: str) -> bool:
        """INSERT OR IGNORE 占位；抢到（rowcount>0）才允许执行真实请求。"""
        with self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO idempotency_keys"
                " (scope, idem_key, request_hash, response_status, response_body, created_at)"
                " VALUES (?, ?, ?, ?, 'null', ?)",
                (scope, key, request_hash, RESERVED_PLACEHOLDER, created_at),
            )
        return cur.rowcount > 0

    def store_response(
        self, scope: str, key: str, response_status: int, response_body_json: str, stored_at: str
    ) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE idempotency_keys SET response_status = ?, response_body = ?,"
                " created_at = ? WHERE scope = ? AND idem_key = ?",
                (response_status, response_body_json, stored_at, scope, key),
            )

    def delete(self, scope: str, key: str) -> None:
        with self._conn:
            self._conn.execute(
                "DELETE FROM idempotency_keys WHERE scope = ? AND idem_key = ?",
                (scope, key),
            )
