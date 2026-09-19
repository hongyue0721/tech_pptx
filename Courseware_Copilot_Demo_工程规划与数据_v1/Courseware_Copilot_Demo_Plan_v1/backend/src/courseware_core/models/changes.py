from typing import Literal

from pydantic import Field

from .base import AwareDatetime, ContractModel, ShortId, WarningMessage
from .deck import DeckSpec
from .evidence import ClaimVerification, UnboundAssertion


class ValidationReport(ContractModel):
    schema_valid: bool
    relations_valid: bool
    layout_valid: bool
    claim_checks: list[ClaimVerification] = Field(default_factory=list, max_length=96)
    warnings: list[WarningMessage] = Field(default_factory=list, max_length=40)
    can_commit: bool
    model_id: str | None = Field(default=None, min_length=1, max_length=128)
    prompt_version: str = Field(min_length=1, max_length=80)
    checked_at: AwareDatetime
    raw_result_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    unbound_assertions: list[UnboundAssertion] = Field(default_factory=list, max_length=64)


class CandidateChange(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    base_version: int = Field(ge=0)
    corpus_revision: int = Field(ge=1)
    status: Literal["ready", "blocked", "committed", "discarded", "stale"]
    kind: Literal["generation", "edit"]
    affected_slide_ids: list[ShortId] = Field(default_factory=list, max_length=16)
    summary: str = Field(min_length=1, max_length=2000)
    candidate: DeckSpec
    validation: ValidationReport
    created_at: AwareDatetime


class CommitRequest(ContractModel):
    base_version: int = Field(ge=0)
    corpus_revision: int = Field(ge=1)
    acknowledged: Literal[True]


class RestoreRequest(ContractModel):
    target_version: int = Field(ge=1)
    base_version: int = Field(ge=1)
    corpus_revision: int = Field(ge=1)
    acknowledged: Literal[True]


class EditRequest(ContractModel):
    instruction: str = Field(min_length=1, max_length=1000)
    target_slide_ids: list[ShortId] = Field(min_length=1, max_length=16)
    base_version: int = Field(ge=1)
    corpus_revision: int = Field(ge=1)


class GenerateRequest(ContractModel):
    plan_id: str = Field(min_length=1, max_length=128)
    base_version: int = Field(ge=0)
    corpus_revision: int = Field(ge=1)
