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
