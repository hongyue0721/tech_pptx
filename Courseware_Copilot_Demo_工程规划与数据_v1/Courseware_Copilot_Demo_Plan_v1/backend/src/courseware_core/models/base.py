from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware ISO8601")
    return value


AwareDatetime = Annotated[datetime, AfterValidator(_require_aware)]

# 元素级约束别名：与 models.schema.json 中 array items 约束逐一对应（review B1）。
ShortId = Annotated[str, StringConstraints(min_length=1, max_length=128)]
GoalIndex = Annotated[int, Field(ge=0, le=7)]
GoalText = Annotated[str, StringConstraints(min_length=1, max_length=240)]
AssumptionText = Annotated[str, StringConstraints(min_length=1, max_length=200)]
WarningMessage = Annotated[str, StringConstraints(min_length=1, max_length=600)]
MissingEvidenceNote = Annotated[str, StringConstraints(min_length=1, max_length=500)]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
