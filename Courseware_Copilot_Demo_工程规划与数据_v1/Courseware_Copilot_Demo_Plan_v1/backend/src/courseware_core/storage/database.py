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


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    with conn:
        conn.executescript(_PROJECTS_DDL + _SCHEMA_META_DDL)
        row = conn.execute("SELECT version FROM schema_meta").fetchone()
        if row is None:
            conn.execute("INSERT INTO schema_meta(version) VALUES (?)", (SCHEMA_VERSION,))
