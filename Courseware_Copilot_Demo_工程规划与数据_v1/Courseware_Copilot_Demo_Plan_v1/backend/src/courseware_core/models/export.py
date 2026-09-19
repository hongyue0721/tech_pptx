from typing import Literal

from pydantic import Field

from .base import ContractModel


class ExportRequest(ContractModel):
    version: int = Field(ge=1)
    format: Literal["pptx"]


class PreviewItem(ContractModel):
    slide_id: str = Field(min_length=1, max_length=128)
    status: Literal["ready", "failed", "pending"]
    source_type: Literal["outline", "pptd_render", "pptx_render"]
    artifact_id: str | None = Field(default=None, min_length=1, max_length=128)
    warning: str | None = Field(default=None, min_length=1, max_length=500)


class PreviewManifest(ContractModel):
    project_id: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1)
    items: list[PreviewItem] = Field(min_length=1, max_length=16)
