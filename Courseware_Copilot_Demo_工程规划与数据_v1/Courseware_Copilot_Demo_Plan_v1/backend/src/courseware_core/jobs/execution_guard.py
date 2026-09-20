"""job 执行协作守卫：取消位轮询、deadline/取消的统一收口（R00-D）。

与 llm.adapter 请求前检查共享同一转换语义（deadline 归 MODEL_TIMEOUT 组、
取消归 JobCancelled），两条路径不得漂移：deadline 是时间预算耗尽（docs/06
项目任务总预算），昂贵动作（模型调用/切块入库）之前必须收口，不烧钱。
"""

import time

from courseware_core.errors import JobCancelled, ModelTimeout
from courseware_core.llm.budget import (
    CallBudget,
    CancelledError,
    DeadlineExceededError,
    JobContext,
)
from courseware_core.storage.job_repository import JobRepository


def make_cancel_check(jobs: JobRepository, job_id: str):
    """轮询取消位（T04-N4 收口：业务 handler 的取消通道）。"""

    def _cancelled() -> bool:
        current = jobs.get(job_id)
        return bool(current and current.cancel_requested)

    return _cancelled


def build_job_context(jobs: JobRepository, job_id: str, max_calls: int) -> JobContext:
    """带真实总 deadline 的执行上下文：jobs.deadline_at 换算 monotonic 剩余秒。

    deadline_at 为 NULL（v1 遗留行）时不检查时间预算，其余语义不变。
    """
    remaining = jobs.get_deadline_remaining(job_id)
    return JobContext(
        budget=CallBudget(max_calls=max_calls),
        cancel_check=make_cancel_check(jobs, job_id),
        deadline=time.monotonic() + remaining if remaining is not None else None,
    )


def guard_active(context: JobContext, stage: str) -> None:
    try:
        context.ensure_active()
    except CancelledError as exc:
        raise JobCancelled({"stage": stage}) from exc
    except DeadlineExceededError as exc:
        raise ModelTimeout("job deadline exceeded", {"stage": stage}) from exc
