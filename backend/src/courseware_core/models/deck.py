from typing import Annotated, Literal, Union

from pydantic import Field

from .base import AssumptionText, AwareDatetime, ContractModel, ShortId
from .common import CourseBrief
from .evidence import Claim, EvidenceSpan


class FactBlock(ContractModel):
    type: Literal["fact"]
    claim_id: str = Field(min_length=1, max_length=128)


class TeachingBlock(ContractModel):
    type: Literal["teaching"]
    text: str = Field(min_length=1, max_length=200)


class IllustrationBlock(ContractModel):
    type: Literal["illustration"]
    text: str = Field(min_length=1, max_length=240)
    assumptions: list[AssumptionText] = Field(min_length=1, max_length=6)
    evidence_refs: list[EvidenceSpan] = Field(default_factory=list, max_length=5)


SlideBlock = Annotated[
    Union[FactBlock, TeachingBlock, IllustrationBlock],
    Field(discriminator="type"),
]

LayoutName = Literal["title", "concept", "two_column", "process_example"]


class Slide(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=40)
    layout: LayoutName
    blocks: list[SlideBlock] = Field(min_length=1, max_length=6)


class DeckSpec(ContractModel):
    schema_version: Literal["1.0.0"]
    project_id: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1)
    corpus_revision: int = Field(ge=1)
    course: CourseBrief
    claims: list[Claim] = Field(default_factory=list, max_length=96)
    slides: list[Slide] = Field(min_length=1, max_length=16)


class ReplaceSlide(ContractModel):
    op: Literal["replace_slide"]
    target_slide_id: str = Field(min_length=1, max_length=128)
    slide: Slide


class SplitSlide(ContractModel):
    op: Literal["split_slide"]
    target_slide_id: str = Field(min_length=1, max_length=128)
    slides: list[Slide] = Field(min_length=2, max_length=2)


class ReorderSlides(ContractModel):
    op: Literal["reorder_slides"]
    slide_ids: list[ShortId] = Field(min_length=1, max_length=16)


PatchOperation = Annotated[
    Union[ReplaceSlide, SplitSlide, ReorderSlides],
    Field(discriminator="op"),
]


class DeckPatch(ContractModel):
    base_version: int = Field(ge=1)
    corpus_revision: int = Field(ge=1)
    operations: list[PatchOperation] = Field(min_length=1, max_length=4)
    claims: list[Claim] = Field(default_factory=list, max_length=32)
    summary: str = Field(min_length=1, max_length=1000)


class DeckVersion(ContractModel):
    project_id: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1)
    corpus_revision: int = Field(ge=1)
    parent_version: int = Field(ge=0)
    restored_from: Annotated[int, Field(ge=1)] | None = None
    created_at: AwareDatetime
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
