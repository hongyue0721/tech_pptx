from typing import Literal

from pydantic import Field, model_validator

from .base import AwareDatetime, ContractModel, GoalIndex, ShortId
from .deck import LayoutName


def normalize_goal_indices(indices: list[int]) -> list[int]:
    """目标索引集合语义的规范形。历史脏数据（T14 实测前端 checkbox 双源 bug
    产出的重复索引）在读侧/回灌侧归一为业务真值=集合；新脏写入已被
    ConfirmPlanRequest validator 拒收。"""
    return sorted(set(indices))


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

    @model_validator(mode="after")
    def _goal_indices_are_sets(self) -> "ConfirmPlanRequest":
        # 接受范围与页面关联目标均为集合语义；重复索引意味着上游状态源失同步
        # （T14 实测抓到前端 checkbox 双源 bug 曾产出 [0,0,1,2,3]），拒绝入库。
        if len(self.accepted_goal_indices) != len(set(self.accepted_goal_indices)):
            raise ValueError("accepted_goal_indices must be unique")
        for slide in self.slides:
            if len(slide.goal_indices) != len(set(slide.goal_indices)):
                raise ValueError(f"slide {slide.id!r} goal_indices must be unique")
        return self
