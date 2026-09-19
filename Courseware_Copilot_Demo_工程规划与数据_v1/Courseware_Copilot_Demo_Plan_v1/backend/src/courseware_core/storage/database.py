import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

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

# jobs：契约 Job 类型 1:1 + 内部追踪列（request_id/worker_id/claimed_at，不出现在对外形状）。
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
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_claim ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(project_id);
"""

# 幂等：scope=会话|项目|路由（docs/07 §2），保留24h（过期懒清理）。
_IDEMPOTENCY_DDL = """
CREATE TABLE IF NOT EXISTS idempotency_keys (
    scope TEXT NOT NULL,
    idem_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    response_status INTEGER NOT NULL,
    response_body TEXT NOT NULL,
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


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    with conn:
        conn.executescript(
            _PROJECTS_DDL
            + _SCHEMA_META_DDL
            + _JOBS_DDL
            + _IDEMPOTENCY_DDL
            + _DECK_VERSIONS_DDL
            + _ARTIFACTS_DDL
        )
        row = conn.execute("SELECT version FROM schema_meta").fetchone()
        if row is None:
            conn.execute("INSERT INTO schema_meta(version) VALUES (?)", (SCHEMA_VERSION,))
