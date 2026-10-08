from typing import Literal, Optional

from pydantic import Field

from .base import ContractModel


class PageWarning(ContractModel):
    pdf_page: int = Field(ge=1)
    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)


class Material(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    original_name: str = Field(min_length=1, max_length=255)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["queued", "parsing", "ready", "failed"]
    pdf_pages: Optional[int] = Field(default=None, ge=1, le=200)
    usable_pages: Optional[int] = Field(default=None, ge=0, le=200)
    corpus_revision: Optional[int] = Field(default=None, ge=0)
    warnings: list[PageWarning] = Field(default_factory=list)
    error_code: Optional[str] = Field(default=None, min_length=1, max_length=80)


class MaterialList(ContractModel):
    materials: list[Material] = Field(min_length=0, max_length=5)
    corpus_revision: int = Field(ge=0)


class MaterialUploadAccepted(ContractModel):
    material_id: str = Field(min_length=1, max_length=128)
    job_id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    duplicate: bool


class DocumentChunk(ContractModel):
    chunk_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    document_id: str = Field(min_length=1, max_length=128)
    corpus_revision: int = Field(ge=0)
    document_name: str = Field(min_length=1, max_length=255)
    pdf_page: int = Field(ge=1)
    printed_page_label: Optional[str] = Field(default=None, min_length=1, max_length=32)
    page_start: int = Field(ge=0)
    page_end: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=1200)
    text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    extractor_version: str = Field(min_length=1, max_length=80)
    tokenizer_version: str = Field(min_length=1, max_length=80)
