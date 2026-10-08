"""T08 plans 三路由：受理 plan job / 读取 LessonPlan / 教师确认。"""

from fastapi import APIRouter, Depends, Request, Response

from courseware_api.dependencies import get_idempotency_service, get_plan_service
from courseware_api.idempotency import execute_idempotent
from courseware_core.models import (
    ConfirmPlanRequest,
    JobAccepted,
    LessonPlan,
    PlanRequest,
)
from courseware_core.services.idempotency_service import IdempotencyService
from courseware_core.services.plan_service import PlanService

router = APIRouter()


@router.post("/projects/{project_id}/plans", status_code=202, response_model=JobAccepted)
def create_plan(
    request: Request,
    project_id: str,
    body: PlanRequest,
    service: PlanService = Depends(get_plan_service),
    idem: IdempotencyService = Depends(get_idempotency_service),
) -> Response:
    def produce(binder) -> tuple[int, dict]:
        accepted = service.create_plan_job(
            project_id, body, request_id=getattr(request.state, "request_id", None),
            binder=binder,
        )
        return 202, accepted.model_dump(mode="json")

    return execute_idempotent(
        request,
        idem,
        "POST /projects/{project_id}/plans",
        project_id,
        body,
        produce,
    )


@router.get("/projects/{project_id}/plans/{plan_id}", response_model=LessonPlan)
def get_plan(
    project_id: str,
    plan_id: str,
    service: PlanService = Depends(get_plan_service),
) -> LessonPlan:
    return service.get_plan(project_id, plan_id)


@router.post(
    "/projects/{project_id}/plans/{plan_id}/confirm", response_model=LessonPlan
)
def confirm_plan(
    request: Request,
    project_id: str,
    plan_id: str,
    body: ConfirmPlanRequest,
    service: PlanService = Depends(get_plan_service),
    idem: IdempotencyService = Depends(get_idempotency_service),
) -> Response:
    def produce(binder) -> tuple[int, dict]:
        plan = service.confirm_plan(project_id, plan_id, body)
        return 200, plan.model_dump(mode="json")

    # scope 含 plan_id：同项目不同计划的确认不得共用键空间。
    return execute_idempotent(
        request,
        idem,
        "POST /projects/{project_id}/plans/{plan_id}/confirm",
        f"{project_id}|{plan_id}",
        body,
        produce,
    )
