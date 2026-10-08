import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from courseware_core.errors import ProjectBusy, ProjectNotFound
from courseware_core.models import DocumentChunk, Material, PageWarning
from courseware_core.storage.job_repository import JobRepository

_WRITE_KINDS_REQUIRING_LOCK = ("parse", "plan", "generate", "edit")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MaterialRepository:
    """materials 表 + parse 编排所需的跨表事务。

    create_with_job 把"占项目写锁 + 插 material + 插 parse job"收进同一事务
    （T04 review N1/N8 的收口点）：崩溃不会留下指向不存在 job 的锁。
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create_with_job(
        self,
        material: Material,
        *,
        job_id: str,
        file_path: str,
        file_size: int,
        request_id: Optional[str] = None,
    ) -> None:
        now = _now_iso()
        with self._conn:
            cur = self._conn.execute(
                "UPDATE projects SET active_job_id = ?, updated_at = ?"
                " WHERE id = ? AND active_job_id IS NULL",
                (job_id, now, material.project_id),
            )
            if cur.rowcount == 0:
                row = self._conn.execute(
                    "SELECT active_job_id FROM projects WHERE id = ?",
                    (material.project_id,),
                ).fetchone()
                if row is None:
                    raise ProjectNotFound({"project_id": material.project_id})
                raise ProjectBusy({"active_job_id": row["active_job_id"]})
            proj = self._conn.execute(
                "SELECT current_version, corpus_revision FROM projects WHERE id = ?",
                (material.project_id,),
            ).fetchone()
            self._conn.execute(
                "INSERT INTO materials (id, project_id, original_name, sha256, status,"
                " pdf_pages, usable_pages, corpus_revision, warnings_json, error_code,"
                " file_path, file_size, job_id, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, 'queued', NULL, NULL, NULL, '[]', NULL, ?, ?, ?, ?, ?)",
                (
                    material.id,
                    material.project_id,
                    material.original_name,
                    material.sha256,
                    file_path,
                    file_size,
                    job_id,
                    now,
                    now,
                ),
            )
            self._conn.execute(
                "INSERT INTO jobs (id, project_id, kind, status, stage, cancel_requested,"
                " base_version, corpus_revision, result_ref, error, llm_calls, request_id,"
                " deadline_at, created_at, updated_at)"
                " VALUES (?, ?, 'parse', 'queued', 'queued', 0, ?, ?, NULL, NULL, 0, ?, ?, ?, ?)",
                (
                    job_id,
                    material.project_id,
                    proj["current_version"],
                    proj["corpus_revision"],
                    request_id,
                    (
                        datetime.now(timezone.utc)
                        + timedelta(seconds=JobRepository.DEFAULT_DEADLINE_SECONDS)
                    ).isoformat(timespec="seconds"),
                    now,
                    now,
                ),
            )

    def get(self, material_id: str) -> Optional[Material]:
        row = self._conn.execute(
            "SELECT * FROM materials WHERE id = ?", (material_id,)
        ).fetchone()
        return self._row_to_material(row) if row else None

    def get_by_job(self, job_id: str) -> Optional[Material]:
        row = self._conn.execute(
            "SELECT * FROM materials WHERE job_id = ?", (job_id,)
        ).fetchone()
        return self._row_to_material(row) if row else None

    def find_duplicate(self, project_id: str, sha256: str) -> Optional[Material]:
        # failed 不算重复（N5）：重传同内容应重新走解析，而非指向失败材料。
        row = self._conn.execute(
            "SELECT * FROM materials WHERE project_id = ? AND sha256 = ?"
            " AND status != 'failed' ORDER BY created_at LIMIT 1",
            (project_id, sha256),
        ).fetchone()
        return self._row_to_material(row) if row else None

    def list_by_project(self, project_id: str) -> list[Material]:
        rows = self._conn.execute(
            "SELECT * FROM materials WHERE project_id = ? ORDER BY created_at, id",
            (project_id,),
        ).fetchall()
        return [self._row_to_material(r) for r in rows]

    def stats(self, project_id: str) -> tuple[int, int]:
        """(文件数, 总字节)——限额检查用（docs/11 §7）。"""
        row = self._conn.execute(
            "SELECT COUNT(*) AS c, COALESCE(SUM(file_size), 0) AS b FROM materials"
            " WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        return row["c"], row["b"]

    def ready_page_budget(self, project_id: str) -> tuple[int, int]:
        """(已入库页数, 已抽取字符数)——parse 时的项目预算余量依据。"""
        row = self._conn.execute(
            "SELECT COALESCE(SUM(pdf_pages), 0) AS pages FROM materials"
            " WHERE project_id = ? AND status = 'ready'",
            (project_id,),
        ).fetchone()
        chars = self._conn.execute(
            "SELECT COALESCE(SUM(LENGTH(text)), 0) AS chars FROM chunks c"
            " JOIN materials m ON m.id = c.document_id"
            " WHERE m.project_id = ? AND m.status = 'ready'",
            (project_id,),
        ).fetchone()
        return row["pages"], chars["chars"]

    def set_parsing(self, material_id: str) -> None:
        now = _now_iso()
        with self._conn:
            self._conn.execute(
                "UPDATE materials SET status = 'parsing', updated_at = ?"
                " WHERE id = ? AND status = 'queued'",
                (now, material_id),
            )

    def save_parsed(
        self,
        material: Material,
        *,
        pdf_pages: int,
        usable_pages: int,
        warnings: list[PageWarning],
        pages: list[dict],
        chunks: list[DocumentChunk],
    ) -> int:
        """成功入库单事务：corpus_revision+1、写 pages/chunks、material→ready。

        corpus 递增与内容落库原子（docs/04 §7），失败整体回滚不留半套索引。
        """
        now = _now_iso()
        with self._conn:
            proj = self._conn.execute(
                "SELECT corpus_revision FROM projects WHERE id = ?",
                (material.project_id,),
            ).fetchone()
            if proj is None:
                raise ProjectNotFound({"project_id": material.project_id})
            new_revision = proj["corpus_revision"] + 1
            self._conn.execute(
                "UPDATE projects SET corpus_revision = ?, updated_at = ? WHERE id = ?",
                (new_revision, now, material.project_id),
            )
            for page in pages:
                self._conn.execute(
                    "INSERT INTO pages (document_id, pdf_page, printed_page_label,"
                    " text, text_sha256, extractor_version, warnings_json)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        material.id,
                        page["pdf_page"],
                        page.get("printed_page_label"),
                        page["text"],
                        page["text_sha256"],
                        page["extractor_version"],
                        json.dumps(page.get("warnings", []), ensure_ascii=False),
                    ),
                )
            for chunk in chunks:
                self._conn.execute(
                    "INSERT INTO chunks (chunk_id, project_id, document_id,"
                    " corpus_revision, pdf_page, page_start, page_end, text,"
                    " text_sha256, extractor_version, tokenizer_version)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        chunk.chunk_id,
                        material.project_id,
                        material.id,
                        new_revision,
                        chunk.pdf_page,
                        chunk.page_start,
                        chunk.page_end,
                        chunk.text,
                        chunk.text_sha256,
                        chunk.extractor_version,
                        chunk.tokenizer_version,
                    ),
                )
            self._conn.execute(
                "UPDATE materials SET status = 'ready', pdf_pages = ?, usable_pages = ?,"
                " corpus_revision = ?, warnings_json = ?, error_code = NULL,"
                " updated_at = ? WHERE id = ?",
                (
                    pdf_pages,
                    usable_pages,
                    new_revision,
                    json.dumps(
                        [w.model_dump(mode="json") for w in warnings],
                        ensure_ascii=False,
                    ),
                    now,
                    material.id,
                ),
            )
        return new_revision

    def set_failed(self, material_id: str, error_code: str) -> None:
        now = _now_iso()
        with self._conn:
            self._conn.execute(
                "UPDATE materials SET status = 'failed', error_code = ?, updated_at = ?"
                " WHERE id = ?",
                (error_code, now, material_id),
            )

    @staticmethod
    def _row_to_material(row: sqlite3.Row) -> Material:
        return Material(
            id=row["id"],
            project_id=row["project_id"],
            original_name=row["original_name"],
            sha256=row["sha256"],
            status=row["status"],
            pdf_pages=row["pdf_pages"],
            usable_pages=row["usable_pages"],
            corpus_revision=row["corpus_revision"],
            warnings=[
                PageWarning.model_validate(w) for w in json.loads(row["warnings_json"])
            ],
            error_code=row["error_code"],
        )
