from typing import Annotated, Literal, Union

from pydantic import Field

from .base import AssumptionText, ContractModel, MissingEvidenceNote, ShortId
from .deck import FactBlock, LayoutName, PatchOperation, Slide, TeachingBlock
from .evidence import EvidenceProposal, UnboundAssertion
from .plan import PlanSlide


class ProposalIllustrationBlock(ContractModel):
    """提案版 illustration 块：evidence_refs 只允许 chunk_id+quote——
    document_id/pdf_page/偏移是服务器权威字段，模型不得自填（docs/04 §19）。"""

    type: Literal["illustration"]
    text: str = Field(min_length=1, max_length=240)
    assumptions: list[AssumptionText] = Field(min_length=1, max_length=6)
    evidence_refs: list[EvidenceProposal] = Field(default_factory=list, max_length=5)


ProposalSlideBlock = Annotated[
    Union[FactBlock, TeachingBlock, ProposalIllustrationBlock],
    Field(discriminator="type"),
]


class ProposalSlide(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=40)
    layout: LayoutName
    blocks: list[ProposalSlideBlock] = Field(min_length=1, max_length=6)


class ClaimProposal(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=160)
    kind: Literal["direct", "derived"]
    evidence_refs: list[EvidenceProposal] = Field(min_length=1, max_length=5)
    rationale: str | None = Field(default=None, min_length=1, max_length=600)


class ContentProposal(ContractModel):
    claims: list[ClaimProposal] = Field(default_factory=list, max_length=96)
    slides: list[ProposalSlide] = Field(min_length=1, max_length=16)
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


class EditProposalOutcome(ContractModel):
    decision: Literal["proposal"]
    proposal: EditProposal


class EditUnsupportedOutcome(ContractModel):
    decision: Literal["unsupported"]
    reason: str = Field(min_length=1, max_length=300)


EditDecision = Annotated[
    Union[EditProposalOutcome, EditUnsupportedOutcome],
    Field(discriminator="decision"),
]


class SemanticCheck(ContractModel):
    claim_id: str = Field(min_length=1, max_length=128)
    status: Literal["supported", "partial", "unsupported", "conflict"]
    reason: str = Field(min_length=1, max_length=600)


class SemanticVerdicts(ContractModel):
    checks: list[SemanticCheck] = Field(min_length=1, max_length=96)
    unbound_assertions: list[UnboundAssertion] = Field(default_factory=list, max_length=64)


class VisibleTextAudit(ContractModel):
    """独立可见文字审计输出（与 claim 语义核验分离）：服务端以
    audited_slide_ids 对必审页集合做双射覆盖门，零 claim 批不得跳过。"""

    audited_slide_ids: list[ShortId] = Field(default_factory=list, max_length=16)
    unbound_assertions: list[UnboundAssertion] = Field(default_factory=list, max_length=64)
