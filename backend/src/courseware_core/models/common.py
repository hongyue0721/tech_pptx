from typing import Literal, Optional

from pydantic import Field

from .base import AwareDatetime, ContractModel, GoalText


class CourseBrief(ContractModel):
    topic: str = Field(min_length=1, max_length=120)
    audience: str = Field(min_length=1, max_length=120)
    duration_minutes: int = Field(ge=10, le=120)
    goals: list[GoalText] = Field(min_length=1, max_length=8)
    target_slides: int = Field(ge=4, le=12)


class CreateProjectRequest(ContractModel):
    course: CourseBrief
    consent_to_cloud_processing: bool


class Project(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    course: CourseBrief
    current_version: int = Field(ge=0)
    corpus_revision: int = Field(ge=0)
    active_job_id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    consent_to_cloud_processing: bool
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ConfirmDeleteRequest(ContractModel):
    acknowledged: Literal[True]


class ErrorDetail(ContractModel):
    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=2000)
    request_id: str = Field(min_length=1, max_length=128)
    details: dict = Field(default_factory=dict)


class ErrorResponse(ContractModel):
    error: ErrorDetail


class Health(ContractModel):
    status: Literal["ok"]
    service: Literal["courseware-copilot"]
    version: str = Field(min_length=1, max_length=40)
