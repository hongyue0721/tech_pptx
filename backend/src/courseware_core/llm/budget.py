"""任务级预算与取消上下文。

一次生成最多24次实际模型请求（含重试、修复和复核），耗尽返回BUDGET_EXCEEDED，
不按剩余进度自动增加费用（docs/06）。所有重试从同一预算扣。
"""

import time
from typing import Callable, Optional


class CallBudget:
    """按实际HTTP请求次数计数的预算（含重试与修复请求）。

    单线程假设：consume为check-then-increment无锁设计（N5），T08引入
    单次模型并发（docs/06最多2）前须先加threading.Lock，否则可静默超支。
    """

    def __init__(self, max_calls: int):
        if max_calls < 1:
            raise ValueError("max_calls must be >= 1")
        self.max_calls = max_calls
        self.used = 0

    @property
    def remaining(self) -> int:
        return self.max_calls - self.used

    def consume(self, count: int = 1) -> None:
        if count > self.remaining:
            raise BudgetExceededError(self.max_calls, self.used)
        self.used += count


class BudgetExceededError(Exception):
    def __init__(self, max_calls: int, used: int):
        super().__init__(f"call budget exhausted: used {used} of {max_calls}")
        self.max_calls = max_calls
        self.used = used


class JobContext:
    """Job执行上下文：deadline/cancel-check/call-budget（docs/18接口契约）。

    deadline用time.monotonic()时刻；cancel_check为轮询取消位的回调。
    docs/18契约还含project/revision/trace三字段（N2），由T08上下文组装
    接入时补齐，用于usage/请求日志落库挂载，本任务不提前造空字段。
    """

    def __init__(
        self,
        budget: CallBudget,
        cancel_check: Optional[Callable[[], bool]] = None,
        deadline: Optional[float] = None,
    ):
        self.budget = budget
        self.cancel_check = cancel_check or (lambda: False)
        self.deadline = deadline

    def ensure_active(self) -> None:
        if self.cancel_check():
            raise CancelledError()
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise DeadlineExceededError()


class CancelledError(Exception):
    pass


class DeadlineExceededError(Exception):
    pass
