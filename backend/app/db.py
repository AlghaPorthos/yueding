from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_by_user_id TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workspace_members (
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('owner', 'editor', 'viewer')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (workspace_id, user_id)
);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    workspace_id TEXT REFERENCES workspaces(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reminders (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    contract_id TEXT NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    version_id TEXT REFERENCES contract_versions(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    due_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'canceled')),
    metadata TEXT NOT NULL DEFAULT '{}',
    created_by_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS checklist_items (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    contract_id TEXT NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    due_at TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'completed', 'canceled')),
    source TEXT NOT NULL DEFAULT 'user',
    created_by_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS draft_versions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    contract_id TEXT NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    base_version_id TEXT REFERENCES contract_versions(id) ON DELETE SET NULL,
    version_number INTEGER NOT NULL CHECK (version_number >= 1),
    content TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'user',
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'confirmed', 'archived')),
    evidence TEXT NOT NULL DEFAULT '[]',
    created_by_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(contract_id, version_number)
);

CREATE TABLE IF NOT EXISTS contracts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    sha256 TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'text/plain',
    workspace_id TEXT REFERENCES workspaces(id) ON DELETE SET NULL,
    created_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contract_versions (
    id TEXT PRIMARY KEY,
    contract_id TEXT NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ready',
    quality_status TEXT NOT NULL DEFAULT 'ready',
    quality_reasons TEXT NOT NULL DEFAULT '[]',
    quality_metrics TEXT NOT NULL DEFAULT '{}',
    page_count INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(contract_id, sha256)
);

CREATE TABLE IF NOT EXISTS document_pages (
    id TEXT PRIMARY KEY,
    version_id TEXT NOT NULL REFERENCES contract_versions(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    text TEXT NOT NULL,
    UNIQUE(version_id, page)
);

CREATE TABLE IF NOT EXISTS text_spans (
    id TEXT PRIMARY KEY,
    page_id TEXT NOT NULL REFERENCES document_pages(id) ON DELETE CASCADE,
    span_id TEXT NOT NULL,
    start_offset INTEGER NOT NULL,
    end_offset INTEGER NOT NULL,
    quote TEXT NOT NULL,
    UNIQUE(page_id, span_id)
);

CREATE TABLE IF NOT EXISTS legal_sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    source_kind TEXT NOT NULL DEFAULT 'external',
    version TEXT NOT NULL,
    jurisdiction TEXT NOT NULL,
    effective_from TEXT,
    effective_to TEXT,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, version)
);

CREATE TABLE IF NOT EXISTS legal_provisions (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES legal_sources(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    source_kind TEXT NOT NULL DEFAULT 'external',
    article TEXT NOT NULL,
    version TEXT NOT NULL,
    jurisdiction TEXT NOT NULL,
    effective_from TEXT,
    effective_to TEXT,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, article, version)
);

CREATE TABLE IF NOT EXISTS legal_alignments (
    id TEXT PRIMARY KEY,
    contract_id TEXT NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    version_id TEXT NOT NULL REFERENCES contract_versions(id) ON DELETE CASCADE,
    clause_type TEXT NOT NULL,
    status TEXT NOT NULL,
    contract_evidence TEXT NOT NULL DEFAULT '[]',
    legal_provisions TEXT NOT NULL DEFAULT '[]',
    reasoning TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(version_id, clause_type)
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    contract_id TEXT,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'canceled')),
    idempotency_key TEXT UNIQUE,
    request_hash TEXT NOT NULL,
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts >= 1),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    progress INTEGER NOT NULL DEFAULT 0 CHECK (progress >= 0 AND progress <= 100),
    worker_id TEXT,
    lease_until TEXT,
    error_code TEXT,
    error_message TEXT,
    result TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    finished_at TEXT,
    next_attempt_at TEXT,
    timeout_seconds INTEGER NOT NULL DEFAULT 600 CHECK (timeout_seconds >= 0),
    dead_letter_at TEXT
);

CREATE TABLE IF NOT EXISTS job_attempts (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
    status TEXT NOT NULL
        CHECK (status IN ('running', 'succeeded', 'failed', 'canceled')),
    worker_id TEXT,
    lease_until TEXT,
    error_code TEXT,
    error_message TEXT,
    result TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_id, attempt_number)
);

CREATE TABLE IF NOT EXISTS job_events (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL CHECK (event_type IN ('created', 'claimed', 'started', 'progress', 'failed', 'succeeded', 'canceled', 'retried', 'dead_lettered')),
    attempt_number INTEGER CHECK (attempt_number >= 1),
    progress INTEGER CHECK (progress >= 0 AND progress <= 100),
    payload TEXT NOT NULL DEFAULT '{}',
    worker_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_id, attempt_number, event_type)
);

CREATE TABLE IF NOT EXISTS llm_invocations (
    id TEXT PRIMARY KEY,
    workspace_id TEXT REFERENCES workspaces(id) ON DELETE SET NULL,
    contract_id TEXT REFERENCES contracts(id) ON DELETE SET NULL,
    version_id TEXT REFERENCES contract_versions(id) ON DELETE SET NULL,
    job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed', 'skipped')),
    input_tokens INTEGER,
    output_tokens INTEGER,
    estimated_cost REAL,
    latency_ms INTEGER,
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status_created
    ON jobs (status, created_at, id);
CREATE INDEX IF NOT EXISTS idx_jobs_lease
    ON jobs (status, lease_until);
CREATE INDEX IF NOT EXISTS idx_job_attempts_job
    ON job_attempts (job_id, attempt_number);

CREATE INDEX IF NOT EXISTS idx_llm_invocations_workspace_created
    ON llm_invocations (workspace_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_llm_invocations_contract_created
    ON llm_invocations (contract_id, created_at, id);
"""


def apply_migrations(path: str | Path) -> None:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=15)
    try:
        connection.executescript(SCHEMA)
        # Early databases made the human-readable span id globally unique.
        # Span ids are scoped by page in the public citation contract, so
        # migrate that constraint before the next contract upload.
        text_spans_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'text_spans'"
        ).fetchone()
        if text_spans_sql and "span_id TEXT NOT NULL UNIQUE" in (text_spans_sql[0] or ""):
            connection.execute("ALTER TABLE text_spans RENAME TO text_spans_legacy")
            connection.execute(
                "CREATE TABLE text_spans ("
                "id TEXT PRIMARY KEY,"
                "page_id TEXT NOT NULL REFERENCES document_pages(id) ON DELETE CASCADE,"
                "span_id TEXT NOT NULL,"
                "start_offset INTEGER NOT NULL,"
                "end_offset INTEGER NOT NULL,"
                "quote TEXT NOT NULL,"
                "UNIQUE(page_id, span_id))"
            )
            connection.execute(
                "INSERT INTO text_spans (id, page_id, span_id, start_offset, end_offset, quote) "
                "SELECT id, page_id, span_id, start_offset, end_offset, quote FROM text_spans_legacy"
            )
            connection.execute("DROP TABLE text_spans_legacy")
        # Preserve databases made by the first text-only prototype.
        contract_columns = {row[1] for row in connection.execute("PRAGMA table_info(contracts)")}
        if "content_type" not in contract_columns:
            connection.execute("ALTER TABLE contracts ADD COLUMN content_type TEXT NOT NULL DEFAULT 'text/plain'")
        if "workspace_id" not in contract_columns:
            connection.execute("ALTER TABLE contracts ADD COLUMN workspace_id TEXT")
        if "created_by_user_id" not in contract_columns:
            connection.execute("ALTER TABLE contracts ADD COLUMN created_by_user_id TEXT")
        version_columns = {row[1] for row in connection.execute("PRAGMA table_info(contract_versions)")}
        if "page_count" not in version_columns:
            connection.execute("ALTER TABLE contract_versions ADD COLUMN page_count INTEGER NOT NULL DEFAULT 1")
        if "quality_status" not in version_columns:
            connection.execute("ALTER TABLE contract_versions ADD COLUMN quality_status TEXT NOT NULL DEFAULT 'ready'")
        if "quality_reasons" not in version_columns:
            connection.execute("ALTER TABLE contract_versions ADD COLUMN quality_reasons TEXT NOT NULL DEFAULT '[]'")
        if "quality_metrics" not in version_columns:
            connection.execute("ALTER TABLE contract_versions ADD COLUMN quality_metrics TEXT NOT NULL DEFAULT '{}'")
        page_columns = {row[1] for row in connection.execute("PRAGMA table_info(document_pages)")}
        if "page" not in page_columns and "page_number" in page_columns:
            connection.execute("ALTER TABLE document_pages RENAME COLUMN page_number TO page")
        legal_source_columns = {row[1] for row in connection.execute("PRAGMA table_info(legal_sources)")}
        if "source_kind" not in legal_source_columns:
            connection.execute("ALTER TABLE legal_sources ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'external'")
        legal_provision_columns = {row[1] for row in connection.execute("PRAGMA table_info(legal_provisions)")}
        if "source_kind" not in legal_provision_columns:
            connection.execute("ALTER TABLE legal_provisions ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'external'")
        job_columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
        if "next_attempt_at" not in job_columns:
            connection.execute("ALTER TABLE jobs ADD COLUMN next_attempt_at TEXT")
        if "timeout_seconds" not in job_columns:
            connection.execute("ALTER TABLE jobs ADD COLUMN timeout_seconds INTEGER NOT NULL DEFAULT 600 CHECK (timeout_seconds >= 0)")
        if "dead_letter_at" not in job_columns:
            connection.execute("ALTER TABLE jobs ADD COLUMN dead_letter_at TEXT")
        job_event_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'job_events'"
        ).fetchone()
        if job_event_exists is None:
            connection.execute(
                "CREATE TABLE job_events ("
                "id TEXT PRIMARY KEY,"
                "job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,"
                "event_type TEXT NOT NULL CHECK (event_type IN ('created', 'claimed', 'started', 'progress', 'failed', 'succeeded', 'canceled', 'retried', 'dead_lettered')),"
                "attempt_number INTEGER CHECK (attempt_number >= 1),"
                "progress INTEGER CHECK (progress >= 0 AND progress <= 100),"
                "payload TEXT NOT NULL DEFAULT '{}',"
                "worker_id TEXT,"
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,"
                "UNIQUE(job_id, attempt_number, event_type))"
            )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_job_events_job_created "
            "ON job_events (job_id, created_at)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_legal_provisions_search "
            "ON legal_provisions (jurisdiction, version, article, id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_contracts_workspace "
            "ON contracts (workspace_id, created_at, id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_workspace_created "
            "ON audit_events (workspace_id, created_at, id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_workspace_members_user "
            "ON workspace_members (user_id, workspace_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_reminders_contract_due "
            "ON reminders (contract_id, status, due_at, id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_checklist_contract_status "
            "ON checklist_items (contract_id, status, due_at, id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_drafts_contract_version "
            "ON draft_versions (contract_id, version_number DESC)"
        )
        connection.commit()
    finally:
        connection.close()


def connect(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
