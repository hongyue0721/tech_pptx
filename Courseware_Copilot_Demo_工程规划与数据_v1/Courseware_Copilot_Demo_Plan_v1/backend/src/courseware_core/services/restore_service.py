"""T12：恢复服务——撤销=以目标版本内容创建新版本（docs/07 §5），不删除历史。"""

import sqlite3

from courseware_core.errors import ProjectBusy, ProjectNotFound
from courseware_core.models import DeckVersion, RestoreRequest
from courseware_core.storage.project_repository import ProjectRepository
from courseware_core.storage.version_repository import VersionRepository


class RestoreService:
    """同步写路径：与生成/编辑共享"指针即锁"单一事实（docs/07 §3）——
    worker finalize/interrupted 恢复均在终态迁移同事务释锁，代码路径不产生
    指向终态的指针，受理期无需查 job 状态（T12 Review N2：单点状态感知会与
    create_write_job CAS、前端 busy 判定口径分裂）。并发正确性由
    commit_version 的 base/corpus CAS 兜底。"""

    def __init__(self, conn: sqlite3.Connection):
        self._projects = ProjectRepository(conn)
        self._versions = VersionRepository(conn)

    def restore(self, project_id: str, request: RestoreRequest) -> DeckVersion:
        project = self._projects.get(project_id)
        if project is None:
            raise ProjectNotFound({"project_id": project_id})
        if project.active_job_id is not None:
            raise ProjectBusy({"active_job_id": project.active_job_id})
        return self._versions.restore(
            project_id,
            target_version=request.target_version,
            expected_base_version=request.base_version,
            expected_corpus_revision=request.corpus_revision,
        )
