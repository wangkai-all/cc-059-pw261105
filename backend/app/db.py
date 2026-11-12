"""SQLite storage for the citation graph workbench."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "citations.db"

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS papers (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    year        INTEGER,
    authors     TEXT NOT NULL DEFAULT '[]',
    venue       TEXT,
    doi_raw     TEXT,
    doi_norm    TEXT,
    topics      TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi_norm);
CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(year);

CREATE TABLE IF NOT EXISTS import_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,
    file_name    TEXT,
    imported_at  TEXT NOT NULL,
    detail       TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS reference_records (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source_paper_id   TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    raw_json          TEXT NOT NULL,
    file_name         TEXT NOT NULL,
    line_no           INTEGER NOT NULL,
    occurrence_index  INTEGER NOT NULL DEFAULT 1,
    fingerprint       TEXT NOT NULL UNIQUE,
    doi_raw           TEXT,
    doi_norm          TEXT,
    title             TEXT,
    year              INTEGER,
    authors           TEXT NOT NULL DEFAULT '[]',
    candidates        TEXT NOT NULL DEFAULT '[]',
    status            TEXT NOT NULL DEFAULT 'pending'
                      CHECK(status IN ('pending', 'resolved')),
    match_type        TEXT NOT NULL DEFAULT 'none'
                      CHECK(match_type IN ('none', 'doi', 'manual')),
    matched_paper_id  TEXT REFERENCES papers(id) ON DELETE SET NULL,
    edge_id           INTEGER,
    import_run_id     INTEGER REFERENCES import_runs(id),
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_refs_status ON reference_records(status);
CREATE INDEX IF NOT EXISTS idx_refs_source ON reference_records(source_paper_id);
CREATE INDEX IF NOT EXISTS idx_refs_target ON reference_records(matched_paper_id);
CREATE INDEX IF NOT EXISTS idx_refs_doi ON reference_records(doi_norm);

CREATE TABLE IF NOT EXISTS edges (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source_paper_id   TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    target_paper_id   TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    occurrence_count  INTEGER NOT NULL DEFAULT 0,
    anomalies         TEXT NOT NULL DEFAULT '[]',
    UNIQUE(source_paper_id, target_paper_id)
);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_paper_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_paper_id);

CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    filters     TEXT NOT NULL,
    result      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_db_path() -> Path:
    """Resolve the DB path at call time so tests can point at a temp file."""
    raw = os.environ.get("CITATION_DB")
    return Path(raw).expanduser() if raw else DEFAULT_DB


@contextmanager
def connect(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    path = Path(db_path) if db_path else get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | str | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def reset_data(conn: sqlite3.Connection) -> None:
    """Delete imported data while keeping the schema in place."""
    conn.execute("DELETE FROM reference_records")
    conn.execute("DELETE FROM edges")
    conn.execute("DELETE FROM snapshots")
    conn.execute("DELETE FROM import_runs")
    conn.execute("DELETE FROM papers")
