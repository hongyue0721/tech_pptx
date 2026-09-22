"""F00 最小读服务：正式 Deck 与证据原文的只读查询（零模型调用、零写副作用）。

deck 缺省版本取 project.current_version（服务器权威指针），版本必须命中该项目
的实际记录——不按目录文件名猜测；evidence 的允许集合语义与 locator 一致：chunk
必须属于当前项目、且落在所请求的累积 revision 内，拒绝超前 revision。
"""

import sqlite3
from typing import Optional

from courseware_core.errors import (
    CorpusChanged,
    DeckNotFound,
    EvidenceNotFound,
    ProjectNotFound,
)
from courseware_core.models import DeckSpec, DocumentChunk, Project
from courseware_core.models.export import PreviewItem, PreviewManifest
from courseware_core.storage.project_repository import ProjectRepository


class ProjectReadService:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._projects = ProjectRepository(conn)

    def get_deck(self, project_id: str, version: Optional[int]) -> DeckSpec:
        project: Project = self._projects.get(project_id)
        if project is None:
            raise ProjectNotFound({"project_id": project_id})
        target = project.current_version if version is None else version
        if target < 1:
            # version=0 / 尚无正式版本：契约语义是"没有正式版本"→404，
            # 不下传仓储（0 永远查不到，也不该被当作合法查询）。
            raise DeckNotFound({"project_id": project_id, "version": target})
        row = self._conn.execute(
            "SELECT deck_json FROM deck_versions"
            " WHERE project_id = ? AND version = ?",
            (project_id, target),
        ).fetchone()
        if row is None:
            raise DeckNotFound({"project_id": project_id, "version": target})
        return DeckSpec.model_validate_json(row["deck_json"])

    def get_previews(self, project_id: str, version: int) -> PreviewManifest:
        """T10 预览 manifest：P0=OUTLINE 级结构预览（docs/08 §预览分级）——
        声明每页来源与状态，不冒充渲染图；损坏版本诚实 failed，绝不盖绿。"""
        project = self._projects.get(project_id)
        if project is None:
            raise ProjectNotFound({"project_id": project_id})
        if version < 1:
            raise DeckNotFound({"project_id": project_id, "version": version})
        row = self._conn.execute(
            "SELECT deck_json FROM deck_versions"
            " WHERE project_id = ? AND version = ?",
            (project_id, version),
        ).fetchone()
        if row is None:
            raise DeckNotFound({"project_id": project_id, "version": version})
        try:
            deck = DeckSpec.model_validate_json(row["deck_json"])
        except Exception:
            return PreviewManifest(
                project_id=project_id,
                version=version,
                items=[
                    PreviewItem(
                        slide_id="deck",
                        status="failed",
                        source_type="outline",
                        artifact_id=None,
                        warning="stored deck could not be parsed; structural preview unavailable for this version",
                    )
                ],
            )
        return PreviewManifest(
            project_id=project_id,
            version=version,
            items=[
                PreviewItem(
                    slide_id=s.id,
                    status="ready",
                    source_type="outline",
                    artifact_id=None,
                    warning=None,
                )
                for s in deck.slides
            ],
        )

    def get_evidence(
        self, project_id: str, chunk_id: str, corpus_revision: int
    ) -> DocumentChunk:
        project = self._projects.get(project_id)
        if project is None:
            raise ProjectNotFound({"project_id": project_id})
        if corpus_revision > project.corpus_revision:
            # 超前 revision=请求了不存在的未来语料，拒绝而非放宽。
            raise CorpusChanged(
                {
                    "project_id": project_id,
                    "requested": corpus_revision,
                    "current": project.corpus_revision,
                }
            )
        row = self._conn.execute(
            "SELECT c.chunk_id, c.project_id, c.document_id, c.corpus_revision,"
            " m.original_name AS document_name, c.pdf_page, p.printed_page_label,"
            " c.page_start, c.page_end, c.text, c.text_sha256,"
            " c.extractor_version, c.tokenizer_version"
            " FROM chunks c"
            " JOIN materials m ON m.id = c.document_id"
            " LEFT JOIN pages p ON p.document_id = c.document_id"
            " AND p.pdf_page = c.pdf_page"
            " WHERE c.chunk_id = ? AND c.project_id = ? AND c.corpus_revision <= ?",
            (chunk_id, project_id, corpus_revision),
        ).fetchone()
        if row is None:
            raise EvidenceNotFound(
                {"project_id": project_id, "chunk_id": chunk_id}
            )
        return DocumentChunk(**dict(row))
