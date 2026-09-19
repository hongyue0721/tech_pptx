from typing import Literal

from pydantic import Field

from .base import ContractModel, MissingEvidenceNote, ShortId
from .deck import PatchOperation, Slide
from .evidence import EvidenceProposal, UnboundAssertion
from .plan import PlanSlide


class ClaimProposal(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=160)
    kind: Literal["direct", "derived"]
    evidence_refs: list[EvidenceProposal] = Field(min_length=1, max_length=5)
    rationale: str | None = Field(default=None, min_length=1, max_length=600)


class ContentProposal(ContractModel):
    claims: list[ClaimProposal] = Field(default_factory=list, max_length=96)
    slides: list[Slide] = Field(min_length=1, max_length=16)
    missing_evidence: list[MissingEvidenceNote] = Field(default_factory=list, max_length=16)


class CoverageNote(ContractModel):
    goal_index: int = Field(ge=0, le=7)
    candidate_chunk_ids: list[ShortId] = Field(default_factory=list, max_length=12)
    note: str = Field(min_length=1, max_length=500)


class PlanProposal(ContractModel):
    slides: list[PlanSlide] = Field(min_length=1, max_length=12)
    coverage_notes: list[CoverageNote] = Field(min_length=1, max_length=8)


class EditProposal(ContractModel):
    operations: list[PatchOperation] = Field(min_length=1, max_length=4)
    claims: list[ClaimProposal] = Field(default_factory=list, max_length=32)
    summary: str = Field(min_length=1, max_length=1000)
    missing_evidence: list[MissingEvidenceNote] = Field(default_factory=list, max_length=16)


class SemanticCheck(ContractModel):
    claim_id: str = Field(min_length=1, max_length=128)
    status: Literal["supported", "partial", "unsupported", "conflict"]
    reason: str = Field(min_length=1, max_length=600)


class SemanticVerdicts(ContractModel):
    checks: list[SemanticCheck] = Field(min_length=1, max_length=96)
    unbound_assertions: list[UnboundAssertion] = Field(default_factory=list, max_length=64)
