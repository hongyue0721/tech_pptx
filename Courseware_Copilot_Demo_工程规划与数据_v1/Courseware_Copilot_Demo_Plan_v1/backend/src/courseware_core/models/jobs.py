from typing import Literal

from pydantic import Field

from .base import AwareDatetime, ContractModel
from .common import ErrorResponse

JobKind = Literal["parse", "plan", "generate", "edit", "export"]
JobStatus = Literal[
    "queued", "running", "blocked", "succeeded", "failed", "cancelled", "interrupted"
]
JobStage = Literal[
    "queued",
    "parsing",
    "retrieving",
    "planning",
    "generating",
    "validating",
    "rendering",
    "exporting",
    "previewing",
    "finished",
]


class JobAccepted(ContractModel):
    job_id: str = Field(min_length=1, max_length=128)


class JobResultRef(ContractModel):
    type: Literal["material", "plan", "change", "artifact"]
    id: str = Field(min_length=1, max_length=128)


class Job(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    kind: JobKind
    status: JobStatus
    stage: JobStage
    cancel_requested: bool
    base_version: int = Field(ge=0)
    corpus_revision: int = Field(ge=0)
    result_ref: JobResultRef | None = None
    error: ErrorResponse | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    llm_calls: int = Field(default=0, ge=0, le=24)
