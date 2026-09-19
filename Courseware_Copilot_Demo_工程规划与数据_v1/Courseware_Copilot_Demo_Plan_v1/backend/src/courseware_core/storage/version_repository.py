import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from courseware_core.errors import (
    CorpusChanged,
    DeckNotFound,
    ProjectNotFound,
    VersionConflict,
)
from courseware_core.models import DeckSpec, DeckVersion


def _canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def semantic_hash(deck: DeckSpec) -> str:
    """内容指纹：忽略 version 等元数据（docs/07 §5），用于撤销/恢复等价比较。"""
    payload = deck.model_dump(mode="json", exclude={"version"})
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


class VersionRepository:
    """不可变版本仓库：版本号服务端分配，(project_id, version) 主键防重；
    commit 在单事务内做 base/corpus CAS + 插版本行 + 移动 current_version 指针。"""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def commit_version(
        self,
        project_id: str,
        deck: DeckSpec,
        expected_base_version: int,
        expected_corpus_revision: int,
        restored_from: Optional[int] = None,
    ) -> DeckVersion:
        """显式 CAS 提交（review N2）：先条件 UPDATE 移动指针，rowcount 判定冲突，
        并发同 base 时失败方得到 VersionConflict 而非原始 IntegrityError。"""
        created_at = datetime.now(timezone.utc).isoformat()
        new_version = expected_base_version + 1
        with self._conn:
            cur = self._conn.execute(
                "UPDATE projects SET current_version = ?, updated_at = ?"
                " WHERE id = ? AND current_version = ? AND corpus_revision = ?",
                (new_version, created_at, project_id, expected_base_version,
                 expected_corpus_revision),
            )
            if cur.rowcount == 0:
                self._raise_conflict(project_id, expected_base_version, expected_corpus_revision)
            if deck.corpus_revision != expected_corpus_revision:
                # 事务回滚，指针不留脏值
                raise CorpusChanged(
                    {
                        "project_id": project_id,
                        "deck_corpus_revision": deck.corpus_revision,
                        "expected": expected_corpus_revision,
                    }
                )
            # 服务端权威：候选里拟议的 version 不作为全局权威，以分配值覆盖。
            stored = deck.model_copy(update={"version": new_version})
            sha = semantic_hash(stored)
            self._conn.execute(
                "INSERT INTO deck_versions (project_id, version, corpus_revision,"
                " parent_version, restored_from, created_at, content_sha256, deck_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    project_id,
                    new_version,
                    stored.corpus_revision,
                    expected_base_version,
                    restored_from,
                    created_at,
                    sha,
                    stored.model_dump_json(),
                ),
            )
        return DeckVersion(
            project_id=project_id,
            version=new_version,
            corpus_revision=stored.corpus_revision,
            parent_version=expected_base_version,
            restored_from=restored_from,
            created_at=created_at,
            content_sha256=sha,
        )

    def _raise_conflict(
        self, project_id: str, expected_base_version: int, expected_corpus_revision: int
    ) -> None:
        row = self._conn.execute(
            "SELECT current_version, corpus_revision FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        if row is None:
            raise ProjectNotFound({"project_id": project_id})
        if row["corpus_revision"] != expected_corpus_revision:
            raise CorpusChanged(
                {
                    "project_id": project_id,
                    "expected": expected_corpus_revision,
                    "actual": row["corpus_revision"],
                }
            )
        raise VersionConflict(
            {
                "project_id": project_id,
                "expected_base_version": expected_base_version,
                "actual_version": row["current_version"],
            }
        )

    def restore(
        self,
        project_id: str,
        target_version: int,
        expected_base_version: int,
        expected_corpus_revision: int,
    ) -> DeckVersion:
        """撤销=以目标版本内容创建新版本（不删除历史），仅允许同 corpus 的版本。"""
        target = self._get_row(project_id, target_version)
        if target is None:
            raise DeckNotFound(
                {"project_id": project_id, "version": target_version}
            )
        deck = DeckSpec.model_validate_json(target["deck_json"])
        return self.commit_version(
            project_id,
            deck,
            expected_base_version=expected_base_version,
            expected_corpus_revision=expected_corpus_revision,
            restored_from=target_version,
        )

    def get_version(self, project_id: str, version: int) -> Optional[DeckVersion]:
        row = self._get_row(project_id, version)
        if row is None:
            return None
        return DeckVersion(
            project_id=row["project_id"],
            version=row["version"],
            corpus_revision=row["corpus_revision"],
            parent_version=row["parent_version"],
            restored_from=row["restored_from"],
            created_at=row["created_at"],
            content_sha256=row["content_sha256"],
        )

    def get_deck(self, project_id: str, version: int) -> Optional[DeckSpec]:
        row = self._get_row(project_id, version)
        if row is None:
            return None
        return DeckSpec.model_validate_json(row["deck_json"])

    def _get_row(self, project_id: str, version: int) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM deck_versions WHERE project_id = ? AND version = ?",
            (project_id, version),
        ).fetchone()
