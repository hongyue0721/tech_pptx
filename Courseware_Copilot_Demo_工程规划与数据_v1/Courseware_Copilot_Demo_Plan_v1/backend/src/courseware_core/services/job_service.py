from datetime import datetime, timezone

from courseware_core.errors import JobNotFound
from courseware_core.models import Job
from courseware_core.storage.job_repository import JobRepository


class JobService:
    """job 状态查询与取消（core 层，不依赖 FastAPI）。"""

    def __init__(self, repo: JobRepository):
        self._repo = repo

    def get_job(self, job_id: str) -> Job:
        job = self._repo.get(job_id)
        if job is None:
            raise JobNotFound({"job_id": job_id})
        return job

    def cancel_job(self, job_id: str) -> Job:
        job = self._repo.request_cancel(job_id)
        if job is None:
            raise JobNotFound({"job_id": job_id})
        return job
