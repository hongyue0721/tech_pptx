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


class ModelConfigError(DomainError):
    """401/403之外的环境与请求构造问题：模型不存在、参数不支持、schema名未知。"""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__("MODEL_CONFIG_ERROR", message, details)


class ModelAuthError(DomainError):
    """401/403：凭据或授权问题，重试无意义，须修正配置。"""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__("MODEL_AUTH_ERROR", message, details)


class ModelUnavailable(DomainError):
    """429/5xx/网络/超时且重试配额耗尽：临时性不可用，可稍后重跑任务。"""

    def __init__(self, message: str, details: Optional[dict] = None):
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
        super().__init__("JOB_CANCELLED", "job was cancelled", details)


class JobDeadlineExceeded(DomainError):
    """任务总预算时间已过：停止后续模型调用。"""

    def __init__(self, details: Optional[dict] = None):
        super().__init__(
            "JOB_DEADLINE_EXCEEDED", "job deadline exceeded", details
        )
