import hashlib
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from courseware_core.errors import (
    ArtifactIntegrityError,
    ArtifactNotFound,
    ProjectNotFound,
)

# artifact_id 直接参与落盘路径，必须拒绝路径分隔符/穿越字符。
_ARTIFACT_ID_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")


def _fsync_dir(directory: Path) -> None:
    """rename 后 fsync 父目录，确保目录项变更也持久化（POSIX）。"""
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@dataclass(frozen=True)
class ArtifactRecord:
    id: str
    project_id: str
    version: int
    corpus_revision: int
    mime: str
    size: int
    sha256: str
    rel_path: str
    renderer_version: Optional[str]
    font_profile: Optional[str]
    validation_status: str
    source_type: str
    created_at: str


class ArtifactStore:
    """产物一致性（docs/07 §7）：文件先原子落盘（tmp+fsync+rename），
    成功之后才写 DB 指针；读取时校验 sha256，指针/文件不一致显式失败不静默。"""

    def __init__(self, conn: sqlite3.Connection, root: Path):
        self._conn = conn
        self.root = Path(root)

    def put(
        self,
        *,
        artifact_id: str,
        project_id: str,
        version: int,
        corpus_revision: int,
        data: bytes,
        mime: str,
        source_type: str,
        validation_status: str,
        renderer_version: Optional[str] = None,
        font_profile: Optional[str] = None,
    ) -> ArtifactRecord:
        if not _ARTIFACT_ID_RE.match(artifact_id):
            raise ValueError(f"unsafe artifact id: {artifact_id!r}")
        if self._conn.execute(
            "SELECT 1 FROM projects WHERE id = ?", (project_id,)
        ).fetchone() is None:
            raise ProjectNotFound({"project_id": project_id})
        sha = hashlib.sha256(data).hexdigest()
        rel_path = f"{project_id}/{artifact_id}"
        target = self.root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f"{target.name}.tmp-{os.getpid()}")
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
        _fsync_dir(target.parent)
        created_at = datetime.now(timezone.utc).isoformat()
        # DB 写失败：文件成为无指针孤儿（可被清理），绝不允许有指针无文件。
        with self._conn:
            self._conn.execute(
                "INSERT INTO artifacts (id, project_id, version, corpus_revision,"
                " mime, size, sha256, rel_path, renderer_version, font_profile,"
                " validation_status, source_type, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    artifact_id,
                    project_id,
                    version,
                    corpus_revision,
                    mime,
                    len(data),
                    sha,
                    rel_path,
                    renderer_version,
                    font_profile,
                    validation_status,
                    source_type,
                    created_at,
                ),
            )
        return ArtifactRecord(
            id=artifact_id,
            project_id=project_id,
            version=version,
            corpus_revision=corpus_revision,
            mime=mime,
            size=len(data),
            sha256=sha,
            rel_path=rel_path,
            renderer_version=renderer_version,
            font_profile=font_profile,
            validation_status=validation_status,
            source_type=source_type,
            created_at=created_at,
        )

    def get(self, artifact_id: str) -> Optional[ArtifactRecord]:
        row = self._conn.execute(
            "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        if row is None:
            return None
        return ArtifactRecord(
            id=row["id"],
            project_id=row["project_id"],
            version=row["version"],
            corpus_revision=row["corpus_revision"],
            mime=row["mime"],
            size=row["size"],
            sha256=row["sha256"],
            rel_path=row["rel_path"],
            renderer_version=row["renderer_version"],
            font_profile=row["font_profile"],
            validation_status=row["validation_status"],
            source_type=row["source_type"],
            created_at=row["created_at"],
        )

    def read_verified(self, artifact_id: str) -> bytes:
        record = self.get(artifact_id)
        if record is None:
            raise ArtifactNotFound({"artifact_id": artifact_id})
        path = self.root / record.rel_path
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ArtifactIntegrityError(
                "artifact file missing for existing pointer",
                {"artifact_id": artifact_id},
            ) from exc
        if hashlib.sha256(data).hexdigest() != record.sha256 or len(data) != record.size:
            raise ArtifactIntegrityError(
                "artifact checksum mismatch", {"artifact_id": artifact_id}
            )
        return data
