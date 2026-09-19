from fastapi import APIRouter, Depends, Request, Response

from courseware_api.dependencies import get_idempotency_service, get_job_service
from courseware_api.idempotency import execute_idempotent
from courseware_core.models import Job
from courseware_core.services.idempotency_service import IdempotencyService
from courseware_core.services.job_service import JobService

router = APIRouter()


@router.get("/jobs/{job_id}", response_model=Job)
def get_job(
    job_id: str,
    service: JobService = Depends(get_job_service),
) -> Job:
    return service.get_job(job_id)


@router.post("/jobs/{job_id}/cancel", response_model=Job)
def cancel_job(
    request: Request,
    job_id: str,
    service: JobService = Depends(get_job_service),
    idem: IdempotencyService = Depends(get_idempotency_service),
) -> Response:
    def produce() -> tuple[int, dict]:
        return 200, service.cancel_job(job_id).model_dump(mode="json")

    # 幂等 scope 的"项目"分量以 job_id 代理（review N11）：
    # cancel 路由无 project 上下文，job_id 全局唯一，作用域等价且更不易串键。
    return execute_idempotent(
        request, idem, "POST /jobs/{job_id}/cancel", job_id, None, produce
    )
