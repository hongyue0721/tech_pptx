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
