from typing import Literal, Optional

from pydantic import Field, model_validator

from .base import ContractModel


class EvidenceProposal(ContractModel):
    chunk_id: str = Field(min_length=1, max_length=128)
    quote: str = Field(min_length=1, max_length=1200)


class EvidenceSpan(ContractModel):
    chunk_id: str = Field(min_length=1, max_length=128)
    document_id: str = Field(min_length=1, max_length=128)
    pdf_page: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=1200)


class Claim(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=160)
    kind: Literal["direct", "derived"]
    evidence_refs: list[EvidenceSpan] = Field(min_length=1, max_length=5)
    rationale: Optional[str] = Field(default=None, min_length=1, max_length=600)

    @model_validator(mode="after")
    def derived_requires_rationale(self) -> "Claim":
        if self.kind == "derived" and not self.rationale:
            raise ValueError("derived claim requires non-empty rationale")
        return self


class ClaimVerification(ContractModel):
    claim_id: str = Field(min_length=1, max_length=128)
    locator_status: Literal["located", "invalid"]
    semantic_status: Literal["supported", "partial", "unsupported", "conflict", "not_checked"]
    reason: str = Field(min_length=1, max_length=600)


class UnboundAssertion(ContractModel):
    slide_id: str = Field(min_length=1, max_length=128)
    field_path: str = Field(min_length=1, max_length=160)
    text: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=600)
