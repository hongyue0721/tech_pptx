from typing import Literal

from pydantic import Field, model_validator

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
    # ADR-12：partial 教师核准通道——仅覆盖"非绿全为 partial"的候选；
    # 清单必须与候选 partial 集精确相等（多核准/漏核准均显式拒绝）。
    # 上限对齐 claim_checks 的 96（partial 集理论可超 16，16 会造成
    # 教师全勾仍 422 的死锁——Review N1）；重复 id 拒绝与 confirm 集合
    # 语义同先例（Review N2 双标纠偏）。
    approved_partial_claim_ids: list[ShortId] = Field(default_factory=list, max_length=96)

    @model_validator(mode="after")
    def _approved_ids_unique(self) -> "CommitRequest":
        ids = self.approved_partial_claim_ids
        if len(ids) != len(set(ids)):
            raise ValueError("approved_partial_claim_ids must be unique")
        return self


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
