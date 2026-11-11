-- Scholarship Intelligence Crawler -- SQLite schema
-- Inspect with: sqlite3 data/scholarships.db ".tables"

CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    records_seen  INTEGER DEFAULT 0,
    new_records   INTEGER DEFAULT 0,
    changed_records INTEGER DEFAULT 0,
    notes         TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS scholarships (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key          TEXT NOT NULL UNIQUE,
    name                TEXT NOT NULL,
    provider            TEXT,
    source_type         TEXT,
    official_source_url TEXT,
    application_url     TEXT,
    discovered_via      TEXT,
    fields_json         TEXT NOT NULL DEFAULT '{}',
    confidence          REAL DEFAULT 0,
    score_components    TEXT DEFAULT '[]',
    lifecycle_status    TEXT DEFAULT 'ACTIVE',
    verification_status TEXT DEFAULT 'REVIEW_REQUIRED',
    first_seen_run      INTEGER,
    last_seen_run       INTEGER,
    last_verified_at    TEXT,
    created_at          TEXT,
    updated_at          TEXT
);

CREATE TABLE IF NOT EXISTS snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    scholarship_id INTEGER NOT NULL REFERENCES scholarships(id),
    run_id        INTEGER NOT NULL REFERENCES runs(id),
    fields_json   TEXT NOT NULL,
    content_hash  TEXT,
    captured_at   TEXT
);

CREATE TABLE IF NOT EXISTS field_evidence (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    scholarship_id INTEGER NOT NULL REFERENCES scholarships(id),
    run_id        INTEGER NOT NULL REFERENCES runs(id),
    field         TEXT NOT NULL,
    value         TEXT,
    evidence      TEXT,
    source_url    TEXT
);

CREATE TABLE IF NOT EXISTS changes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    scholarship_id INTEGER NOT NULL REFERENCES scholarships(id),
    run_id        INTEGER NOT NULL REFERENCES runs(id),
    field         TEXT NOT NULL,
    old_value     TEXT,
    new_value     TEXT,
    detected_at   TEXT,
    source_url    TEXT,
    evidence      TEXT
);

CREATE INDEX IF NOT EXISTS idx_snap_scholarship ON snapshots(scholarship_id, run_id);
CREATE INDEX IF NOT EXISTS idx_changes_scholarship ON changes(scholarship_id);
CREATE INDEX IF NOT EXISTS idx_evidence_scholarship ON field_evidence(scholarship_id);
