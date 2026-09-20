from typing import Optional


class DomainError(Exception):
    """core层结构化错误：由HTTP/CLI各自映射，不渗透到对方语义。"""

    def __init__(self, code: str, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class ProjectNotFound(DomainError):
    def __init__(self, details: Optional[dict] = None):
        super().__init__("PROJECT_NOT_FOUND", "project not found", details)


class ProjectBusy(DomainError):
    def __init__(self, details: Optional[dict] = None):
        super().__init__("PROJECT_BUSY", "project has an active job", details)


class ValidationFailed(DomainError):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__("VALIDATION_ERROR", message, details)


class JobNotFound(DomainError):
    def __init__(self, details: Optional[dict] = None):
        super().__init__("JOB_NOT_FOUND", "job not found", details)


class IdempotencyConflict(DomainError):
    def __init__(self, details: Optional[dict] = None):
        super().__init__(
            "IDEMPOTENCY_CONFLICT",
            "idempotency key reused with a different request",
            details,
        )


class VersionConflict(DomainError):
    def __init__(self, details: Optional[dict] = None):
        super().__init__(
            "VERSION_CONFLICT", "project version moved beyond expected base", details
        )


class CorpusChanged(DomainError):
    def __init__(self, details: Optional[dict] = None):
        super().__init__(
            "CORPUS_CHANGED", "corpus revision does not match expected", details
        )


class DeckNotFound(DomainError):
    def __init__(self, details: Optional[dict] = None):
        super().__init__("DECK_NOT_FOUND", "deck version not found", details)


class ArtifactNotFound(DomainError):
    def __init__(self, details: Optional[dict] = None):
        super().__init__("ARTIFACT_NOT_FOUND", "artifact not found", details)


class ArtifactIntegrityError(DomainError):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__("ARTIFACT_INTEGRITY", message, details)


class WorkerAlreadyRunning(DomainError):
    def __init__(self, details: Optional[dict] = None):
        super().__init__(
            "WORKER_ALREADY_RUNNING", "another job worker holds the lock", details
        )


class ModelProtocolError(DomainError):
    """400/404/不支持参数/本地LLM配置缺失：确定性请求问题，重试无意义（api.md 502组）。"""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__("MODEL_PROTOCOL_ERROR", message, details)


class ModelAuthError(DomainError):
    """401/403：凭据或授权问题，重试无意义，须修正配置。"""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__("MODEL_AUTH_ERROR", message, details)


class ModelRateLimited(DomainError):
    """429且退避重试后仍限流（api.md 503组，受预算限制重试）。"""

    def __init__(self, message: str = "model rate limited", details: Optional[dict] = None):
        super().__init__("MODEL_RATE_LIMIT", message, details)


class ModelTimeout(DomainError):
    """读/连超时重试耗尽，或任务deadline超过（api.md 503组）。"""

    def __init__(self, message: str = "model call timed out", details: Optional[dict] = None):
        super().__init__("MODEL_TIMEOUT", message, details)


class ModelUnavailable(DomainError):
    """5xx/连接失败且退避重试耗尽：供应商临时故障，可稍后重跑任务。"""

    def __init__(self, message: str = "model temporarily unavailable", details: Optional[dict] = None):
        super().__init__("MODEL_UNAVAILABLE", message, details)


class ModelOutputInvalid(DomainError):
    """JSON解析/schema校验失败且修复机会已用尽。"""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__("MODEL_OUTPUT_INVALID", message, details)


class BudgetExceeded(DomainError):
    """请求次数预算耗尽：不按剩余进度自动增加费用。"""

    def __init__(self, details: Optional[dict] = None):
        super().__init__("BUDGET_EXCEEDED", "model call budget exhausted", details)


class JobCancelled(DomainError):
    """取消位已置：停止后续步骤。供应商已接收的推理可能仍计费。"""

    def __init__(self, details: Optional[dict] = None):
        super().__init__("CANCELLED", "job was cancelled", details)


class PlanNotFound(DomainError):
    def __init__(self, details: Optional[dict] = None):
        super().__init__("PLAN_NOT_FOUND", "lesson plan not found", details)


class InsufficientEvidence(DomainError):
    """资料不足：job置blocked（非failed），保持旧版本、补材料或收窄目标（api.md:59）。"""

    def __init__(self, message: str = "insufficient evidence in materials", details: Optional[dict] = None):
        super().__init__("INSUFFICIENT_EVIDENCE", message, details)


class ConsentRequired(DomainError):
    """云处理告知未确认（consent=false）：拒绝进入任何云推理（api.md §创建与资料）。

    本地解析不受影响；教师须在创建项目时确认告知，P0 无项目更新路径。
    """

    def __init__(self, details: Optional[dict] = None):
        super().__init__(
            "CONSENT_REQUIRED",
            "cloud processing consent not granted for this project",
            details,
        )


class PlanNotConfirmed(DomainError):
    """生成门禁：未确认（或已 stale）的大纲计划不得进入候选生成（api.md:78）。"""

    def __init__(self, details: Optional[dict] = None):
        super().__init__(
            "PLAN_NOT_CONFIRMED", "lesson plan is not confirmed for this corpus", details
        )


class ChangeNotFound(DomainError):
    """候选变更不存在或不属于该项目（不泄露跨项目存在性，api.md 404 组）。"""

    def __init__(self, details: Optional[dict] = None):
        super().__init__("CHANGE_NOT_FOUND", "candidate change not found", details)


class ChangeNotCommittable(DomainError):
    """候选不可应用：blocked/已提交/核验未全过（docs/04:41 可执行门）。"""

    def __init__(self, details: Optional[dict] = None):
        super().__init__(
            "CHANGE_NOT_COMMITTABLE", "candidate change is not committable", details
        )
