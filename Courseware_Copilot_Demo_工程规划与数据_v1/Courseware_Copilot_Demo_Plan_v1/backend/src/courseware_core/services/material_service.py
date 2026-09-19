"""材料上传与解析编排（docs/04 §11、docs/11 §5-§11）。

core 服务，不依赖 FastAPI：限额/去重/文件名转义/原子落盘/占锁建 job 同事务，
handle_parse 作为 worker 的 parse handler 注册。
"""

import hashlib
import secrets
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from courseware_core.errors import DomainError, ProjectNotFound, ValidationFailed
from courseware_core.materials.chunker import split_page
from courseware_core.materials.parser import (
    EXTRACTOR_VERSION,
    PROJECT_MAX_CHARS,
    PROJECT_MAX_PAGES,
    ParseLimits,
    parse_pdf,
)
from courseware_core.models import (
    DocumentChunk,
    Job,
    JobResultRef,
    Material,
    MaterialList,
    MaterialUploadAccepted,
    PageWarning,
)
from courseware_core.storage.material_repository import MaterialRepository
from courseware_core.storage.project_repository import ProjectRepository

PDF_MAGIC = b"%PDF-"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class ProjectLimits:
    """本项目产品限额（docs/11 §7），非底层库保证；测试注入小值。"""

    max_file_bytes: int = MAX_UPLOAD_BYTES
    max_files: int = 5
    max_project_bytes: int = 100 * 1024 * 1024
    max_project_pages: int = PROJECT_MAX_PAGES
    max_project_chars: int = PROJECT_MAX_CHARS


def sanitize_display_name(name: str) -> str:
    """文件名只作展示并转义（docs/04 §9），绝不参与路径。"""
    name = unicodedata.normalize("NFC", name)
    name = Path(name).name
    name = "".join(c for c in name if c.isprintable() and c not in "/\\")
    name = name.replace("..", "").strip()
    if not name:
        name = "unnamed.pdf"
    return name[:255]


class MaterialService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        materials_root: Path,
        limits: ProjectLimits = ProjectLimits(),
    ):
        self._conn = conn
        self._materials = MaterialRepository(conn)
        self._projects = ProjectRepository(conn)
        self.materials_root = Path(materials_root)
        self._limits = limits

    def upload(
        self, *, project_id: str, original_name: str, data: bytes
    ) -> MaterialUploadAccepted:
        if self._conn.execute(
            "SELECT 1 FROM projects WHERE id = ?", (project_id,)
        ).fetchone() is None:
            raise ProjectNotFound({"project_id": project_id})
        if len(data) > self._limits.max_file_bytes:
            raise DomainError(
                "PAYLOAD_TOO_LARGE",
                f"file exceeds {self._limits.max_file_bytes} bytes per file",
            )
        if not data.startswith(PDF_MAGIC):
            # 验证 PDF 结构，不只扩展名/MIME（docs/11 §9）。
            raise DomainError("UNSUPPORTED_FILE", "upload is not a PDF by magic bytes")

        sha = hashlib.sha256(data).hexdigest()
        # 去重先于配额检查（review B1）：重复命中不新增文件、不消费配额，
        # "项目已满 + 重传同内容"必须返回原 material 而非 413。
        # failed 不算重复（N5）：重传同内容重新走解析；失败件配额回收仅靠整项目删除。
        duplicate = self._materials.find_duplicate(project_id, sha)
        if duplicate is not None:
            # 同项目同文件重复上传返回原 material，不增加 revision（docs/04 §9）。
            return MaterialUploadAccepted(
                material_id=duplicate.id, job_id=None, duplicate=True
            )
        file_count, total_bytes = self._materials.stats(project_id)
        if file_count >= self._limits.max_files:
            raise DomainError(
                "PAYLOAD_TOO_LARGE", f"project allows at most {self._limits.max_files} files"
            )
        if total_bytes + len(data) > self._limits.max_project_bytes:
            raise DomainError(
                "PAYLOAD_TOO_LARGE", "project total storage limit exceeded"
            )

        material_id = f"mat_{secrets.token_hex(16)}"
        job_id = f"job_{secrets.token_hex(16)}"
        material = Material(
            id=material_id,
            project_id=project_id,
            original_name=sanitize_display_name(original_name),
            sha256=sha,
            status="queued",
            pdf_pages=None,
            usable_pages=None,
            corpus_revision=None,
            warnings=[],
            error_code=None,
        )
        # 先原子落盘再写指针：DB 失败只留无指针孤儿文件（启动 GC 清理，N4），
        # 绝不有指针无文件。
        self._store_file(material_id, data)
        self._materials.create_with_job(
            material,
            job_id=job_id,
            file_path=f"{material_id}.pdf",
            file_size=len(data),
        )
        return MaterialUploadAccepted(
            material_id=material_id, job_id=job_id, duplicate=False
        )

    def material_path(self, material_id: str) -> Path:
        path = (self.materials_root / f"{material_id}.pdf").resolve()
        root = self.materials_root.resolve()
        if not path.is_relative_to(root):
            raise ValidationFailed("material path escapes storage root")
        return path

    def list_materials(self, project_id: str) -> MaterialList:
        project = self._projects.get(project_id)
        if project is None:
            raise ProjectNotFound({"project_id": project_id})
        return MaterialList(
            materials=self._materials.list_by_project(project_id),
            corpus_revision=project.corpus_revision,
        )

    def handle_parse(self, job: Job) -> JobResultRef:
        """worker parse handler：逐页抽取+切块，成功后 corpus_revision+1。

        失败路径把 material 收口为 failed 再抛错（worker 收口 job failed 并释锁），
        任何异常类型都不留 parsing 僵尸行（review N3）；未成功入库不推进 corpus（docs/04 §7）。
        """
        material = self._materials.get_by_job(job.id)
        if material is None:
            raise ValidationFailed(
                "parse job without material row", {"job_id": job.id}
            )
        self._materials.set_parsing(material.id)
        try:
            return self._parse_and_store(job, material)
        except DomainError as exc:
            self._materials.set_failed(material.id, exc.code)
            raise
        except Exception:
            self._materials.set_failed(material.id, "INTERNAL_ERROR")
            raise

    def _parse_and_store(self, job: Job, material: Material) -> JobResultRef:
        used_pages, used_chars = self._materials.ready_page_budget(material.project_id)
        limits = ParseLimits(
            max_pages=max(self._limits.max_project_pages - used_pages, 1),
            max_chars=max(self._limits.max_project_chars - used_chars, 1),
        )
        parsed = parse_pdf(self.material_path(material.id), limits)

        pages_payload = [
            {
                "pdf_page": page.pdf_page,
                "printed_page_label": page.printed_page_label,
                "text": page.text,
                "text_sha256": hashlib.sha256(page.text.encode("utf-8")).hexdigest(),
                "extractor_version": EXTRACTOR_VERSION,
                "warnings": [w.model_dump(mode="json") for w in page.warnings],
            }
            for page in parsed.pages
        ]
        # 直接传 DocumentChunk 对象（N6）：corpus_revision 由 save_parsed 单事务分配，
        # 不经过会静默丢弃占位值的 dict 通道。
        chunks_payload: list[DocumentChunk] = []
        document_warnings: list[PageWarning] = []
        for page in parsed.pages:
            chunks_payload.extend(
                split_page(
                    page,
                    project_id=material.project_id,
                    document_id=material.id,
                    document_name=material.original_name,
                    corpus_revision=0,
                )
            )
            document_warnings.extend(page.warnings)

        self._materials.save_parsed(
            material,
            pdf_pages=parsed.pdf_pages,
            usable_pages=parsed.usable_pages,
            warnings=document_warnings,
            pages=pages_payload,
            chunks=chunks_payload,
        )
        return JobResultRef(type="material", id=material.id)

    def _store_file(self, material_id: str, data: bytes) -> None:
        import os

        self.materials_root.mkdir(parents=True, exist_ok=True)
        target = self.material_path(material_id)
        tmp = target.with_name(f"{target.name}.tmp-{os.getpid()}")
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
        fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
