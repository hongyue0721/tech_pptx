"""R00-D：v1 老库平滑迁移（jobs.deadline_at / idempotency_keys.operation_ref）。"""

import sqlite3

from courseware_core.storage.database import SCHEMA_VERSION, connect, init_db

_V1_JOBS = """
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    base_version INTEGER NOT NULL,
    corpus_revision INTEGER NOT NULL,
    result_ref TEXT,
    error TEXT,
    llm_calls INTEGER NOT NULL DEFAULT 0,
    request_id TEXT,
    worker_id TEXT,
    claimed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_V1_IDEM = """
CREATE TABLE idempotency_keys (
    scope TEXT NOT NULL,
    idem_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    response_status INTEGER NOT NULL,
    response_body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (scope, idem_key)
);
"""


def test_init_db_migrates_v1_schema_without_losing_rows(tmp_path):
    db = tmp_path / "v1.db"
    raw = sqlite3.connect(db)
    raw.executescript(
        "CREATE TABLE schema_meta (version INTEGER NOT NULL);"
        "INSERT INTO schema_meta(version) VALUES (1);"
        + _V1_JOBS
        + _V1_IDEM
    )
    raw.execute(
        "INSERT INTO idempotency_keys VALUES"
        " ('s','k','h',202,'{\"job_id\":\"job_old\"}','2026-09-19T00:00:00+00:00')"
    )
    raw.commit()
    raw.close()

    conn = connect(db)
    init_db(conn)
    jobs_cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    idem_cols = {r[1] for r in conn.execute("PRAGMA table_info(idempotency_keys)")}
    assert "deadline_at" in jobs_cols
    assert "operation_ref" in idem_cols
    row = conn.execute(
        "SELECT * FROM idempotency_keys WHERE idem_key = 'k'"
    ).fetchone()
    assert row["response_status"] == 202  # 既有数据原样保留
    assert row["operation_ref"] is None
    assert conn.execute("SELECT version FROM schema_meta").fetchone()[0] == SCHEMA_VERSION
    conn.close()
