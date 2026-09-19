from typing import Literal

from pydantic import Field

from .base import AwareDatetime, ContractModel, GoalIndex, ShortId
from .deck import LayoutName


class ObjectiveCoverage(ContractModel):
    goal_index: int = Field(ge=0, le=7)
    status: Literal["supported", "partial", "unsupported", "conflict"]
    chunk_ids: list[ShortId] = Field(default_factory=list, max_length=20)
    note: str = Field(default="", max_length=500)


class PlanSlide(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=40)
    purpose: str = Field(min_length=1, max_length=240)
    layout: LayoutName
    goal_indices: list[GoalIndex] = Field(default_factory=list, max_length=8)
    evidence_chunk_ids: list[ShortId] = Field(default_factory=list, max_length=12)


class PlanRequest(ContractModel):
    corpus_revision: int = Field(ge=1)


class LessonPlan(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    corpus_revision: int = Field(ge=1)
    status: Literal["draft", "needs_material", "confirmed", "stale"]
    coverage: list[ObjectiveCoverage] = Field(min_length=1, max_length=8)
    slides: list[PlanSlide] = Field(min_length=1, max_length=12)
    accepted_goal_indices: list[GoalIndex] = Field(default_factory=list, max_length=8)
    created_at: AwareDatetime


class ConfirmPlanRequest(ContractModel):
    corpus_revision: int = Field(ge=1)
    slides: list[PlanSlide] = Field(min_length=1, max_length=12)
    accepted_goal_indices: list[GoalIndex] = Field(min_length=1, max_length=8)
    acknowledged: Literal[True]
