import sqlite3
from pathlib import Path

SCHEMA_VERSION = 4

_PROJECTS_DDL = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    course_json TEXT NOT NULL,
    current_version INTEGER NOT NULL DEFAULT 0,
    corpus_revision INTEGER NOT NULL DEFAULT 0,
    active_job_id TEXT,
    consent_to_cloud_processing INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_SCHEMA_META_DDL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER NOT NULL
);
"""

# jobs：契约 Job 类型 1:1 + 内部追踪列（request_id/worker_id/claimed_at/deadline_at/
# params_json，不出现在对外形状）。deadline_at=受理时计算的任务总预算时刻（docs/06，R00-D）；
# params_json=T09 受理参数（plan_id/base_version），执行侧按 job 精确取参、不猜。
# 状态/stage 的 CHECK 与 contracts/models.schema.json enum 对齐，防脏状态入库。
_JOBS_DDL = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('parse','plan','generate','edit','export')),
    status TEXT NOT NULL CHECK (status IN
        ('queued','running','blocked','succeeded','failed','cancelled','interrupted')),
    stage TEXT NOT NULL CHECK (stage IN
        ('queued','parsing','retrieving','planning','generating',
         'validating','rendering','exporting','previewing','finished')),
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0,1)),
    base_version INTEGER NOT NULL CHECK (base_version >= 0),
    corpus_revision INTEGER NOT NULL CHECK (corpus_revision >= 0),
    result_ref TEXT,
    error TEXT,
    llm_calls INTEGER NOT NULL DEFAULT 0 CHECK (llm_calls BETWEEN 0 AND 24),
    request_id TEXT,
    worker_id TEXT,
    claimed_at TEXT,
    deadline_at TEXT,
    params_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_claim ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(project_id);
"""

# 幂等：scope=会话|项目|路由（docs/07 §2），保留24h（过期懒清理）。
# operation_ref（R00-D）：占位行锚定的业务资源 id（如 job_id）。锚点与业务写入
# 同事务提交——"响应缓存未写就崩溃"后同键重试可凭锚点找回原业务结果。
_IDEMPOTENCY_DDL = """
CREATE TABLE IF NOT EXISTS idempotency_keys (
    scope TEXT NOT NULL,
    idem_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    response_status INTEGER NOT NULL,
    response_body TEXT NOT NULL,
    operation_ref TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (scope, idem_key)
);
"""

# 版本仓库：不可变行，(project_id, version) 主键；current_version 指针在 projects 表。
_DECK_VERSIONS_DDL = """
CREATE TABLE IF NOT EXISTS deck_versions (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK (version >= 1),
    corpus_revision INTEGER NOT NULL CHECK (corpus_revision >= 1),
    parent_version INTEGER NOT NULL CHECK (parent_version >= 0),
    restored_from INTEGER CHECK (restored_from IS NULL OR restored_from >= 1),
    created_at TEXT NOT NULL,
    content_sha256 TEXT NOT NULL CHECK (content_sha256 GLOB '[a-f0-9]*' AND length(content_sha256) = 64),
    deck_json TEXT NOT NULL,
    PRIMARY KEY (project_id, version)
);
"""

# artifact 指针：文件先原子落盘，指针行随后方可查；读取时校验 sha256。
_ARTIFACTS_DDL = """
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK (version >= 1),
    corpus_revision INTEGER NOT NULL CHECK (corpus_revision >= 1),
    mime TEXT NOT NULL,
    size INTEGER NOT NULL CHECK (size >= 0),
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    rel_path TEXT NOT NULL,
    renderer_version TEXT,
    font_profile TEXT,
    validation_status TEXT NOT NULL CHECK (validation_status IN ('passed','failed','not_applicable')),
    source_type TEXT NOT NULL CHECK (source_type IN ('export','preview','render')),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artifacts_project_version ON artifacts(project_id, version);
"""


# T05：材料/页/切块。SQLite 不存大文件内容（docs/04 §47），file_path 指向受控目录原子落盘原件。
_MATERIALS_DDL = """
CREATE TABLE IF NOT EXISTS materials (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    original_name TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    status TEXT NOT NULL CHECK (status IN ('queued','parsing','ready','failed')),
    pdf_pages INTEGER CHECK (pdf_pages IS NULL OR pdf_pages >= 1),
    usable_pages INTEGER CHECK (usable_pages IS NULL OR usable_pages >= 0),
    corpus_revision INTEGER,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    error_code TEXT,
    file_path TEXT NOT NULL,
    file_size INTEGER NOT NULL CHECK (file_size >= 0),
    job_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_materials_project ON materials(project_id);
CREATE INDEX IF NOT EXISTS idx_materials_project_sha ON materials(project_id, sha256);
"""

_PAGES_DDL = """
CREATE TABLE IF NOT EXISTS pages (
    document_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    pdf_page INTEGER NOT NULL CHECK (pdf_page >= 1),
    printed_page_label TEXT,
    text TEXT NOT NULL,
    text_sha256 TEXT NOT NULL CHECK (length(text_sha256) = 64),
    extractor_version TEXT NOT NULL,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (document_id, pdf_page)
);
"""

_CHUNKS_DDL = """
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    corpus_revision INTEGER NOT NULL CHECK (corpus_revision >= 0),
    pdf_page INTEGER NOT NULL CHECK (pdf_page >= 1),
    page_start INTEGER NOT NULL CHECK (page_start >= 0),
    page_end INTEGER NOT NULL CHECK (page_end >= 1),
    text TEXT NOT NULL,
    text_sha256 TEXT NOT NULL CHECK (length(text_sha256) = 64),
    extractor_version TEXT NOT NULL,
    tokenizer_version TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_project_rev ON chunks(project_id, corpus_revision);
"""

# T08：大纲（LessonPlan）。整对象随 plan_json 持久化（对齐 deck_versions 存法），
# status/corpus_revision 冗余成列供查询与CAS；status 四态对齐 schema enum；
# corpus_revision 绑定生成时的语料快照，前进即过期（docs/07 §21）。
_PLANS_DDL = """
CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    corpus_revision INTEGER NOT NULL CHECK (corpus_revision >= 1),
    status TEXT NOT NULL CHECK (status IN ('draft','needs_material','confirmed','stale')),
    plan_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plans_project_rev ON plans(project_id, corpus_revision);
"""


# T09：候选变更（CandidateChange）。整对象随 change_json 持久化（对齐 plans 存法），
# status/kind 冗余成列供查询与 CAS；status 五态、kind 两态与 models.schema.json enum 对齐。
# 生成与应用分离：committed 仅由 commit 的 CAS 路径写入。
_CHANGES_DDL = """
CREATE TABLE IF NOT EXISTS changes (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    base_version INTEGER NOT NULL CHECK (base_version >= 0),
    corpus_revision INTEGER NOT NULL CHECK (corpus_revision >= 1),
    status TEXT NOT NULL CHECK (status IN
        ('ready','blocked','committed','discarded','stale')),
    kind TEXT NOT NULL CHECK (kind IN ('generation','edit')),
    change_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_changes_project ON changes(project_id, created_at);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """v1→v2（R00-D）：补 jobs.deadline_at 与 idempotency_keys.operation_ref。

    新库 DDL 已含列；仅老库 PRAGMA 检查后 ALTER。SQLite ADD COLUMN 可空列
    为元数据操作，不重写数据。
    """
    job_cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    if "deadline_at" not in job_cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN deadline_at TEXT")
    idem_cols = {r[1] for r in conn.execute("PRAGMA table_info(idempotency_keys)")}
    if "operation_ref" not in idem_cols:
        conn.execute("ALTER TABLE idempotency_keys ADD COLUMN operation_ref TEXT")


def _migrate_columns(conn: sqlite3.Connection) -> None:
    """列级迁移统一入口：v1→v2 两列 + v4 jobs.params_json（幂等 PRAGMA 检查）。"""
    _migrate_v1_to_v2(conn)
    job_cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    if "params_json" not in job_cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN params_json TEXT")


def init_db(conn: sqlite3.Connection) -> None:
    with conn:
        conn.executescript(
            _PROJECTS_DDL
            + _SCHEMA_META_DDL
            + _JOBS_DDL
            + _IDEMPOTENCY_DDL
            + _DECK_VERSIONS_DDL
            + _ARTIFACTS_DDL
            + _MATERIALS_DDL
            + _PAGES_DDL
            + _CHUNKS_DDL
            + _PLANS_DDL
            + _CHANGES_DDL
        )
        row = conn.execute("SELECT version FROM schema_meta").fetchone()
        if row is None:
            conn.execute("INSERT INTO schema_meta(version) VALUES (?)", (SCHEMA_VERSION,))
        else:
            # 列级迁移幂等（PRAGMA 检查后 ALTER）；新表由上方 CREATE IF NOT EXISTS 补齐。
            if row[0] < SCHEMA_VERSION:
                _migrate_columns(conn)
                conn.execute("UPDATE schema_meta SET version = ?", (SCHEMA_VERSION,))
