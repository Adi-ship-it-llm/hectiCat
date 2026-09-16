"""Local runtime foundation for hectiCat.

Later features add resume ingestion, job scoring, and browser automation.  This
module intentionally contains only the local server, durable schema, and a
minimal dashboard needed to operate those features safely.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse


BASE = Path(os.environ.get("HECTICAT_HOME", "~/hectiCat")).expanduser()
DB = BASE / "data" / "hecticat.sqlite3"
BROWSER_PROFILE = BASE / "browser-profile"

app = FastAPI(title="hectiCat", version="0.1.0")


def now() -> str:
    """Return a timezone-aware, sortable timestamp for persisted records."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def db() -> sqlite3.Connection:
    """Open the local database with rows addressable by column name."""
    DB.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    """Create the durable product schema without modifying existing records."""
    connection = db()
    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS resumes (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                filename TEXT NOT NULL,
                text TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY,
                source TEXT,
                url TEXT NOT NULL UNIQUE,
                company TEXT,
                title TEXT,
                location TEXT,
                salary TEXT,
                description TEXT NOT NULL DEFAULT '',
                requirements TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'new',
                ats_score REAL,
                fit_score REAL,
                selected_resume_id INTEGER REFERENCES resumes(id),
                discovered_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS evaluations (
                id INTEGER PRIMARY KEY,
                job_id INTEGER NOT NULL REFERENCES jobs(id),
                resume_id INTEGER NOT NULL REFERENCES resumes(id),
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(job_id, resume_id)
            );

            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY,
                job_id INTEGER NOT NULL REFERENCES jobs(id),
                resume_id INTEGER NOT NULL REFERENCES resumes(id),
                status TEXT NOT NULL DEFAULT 'draft',
                fields_json TEXT NOT NULL DEFAULT '{}',
                notes TEXT,
                created_at TEXT NOT NULL,
                submitted_at TEXT,
                approved_hash TEXT
            );

            CREATE TABLE IF NOT EXISTS profile (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS workflows (
                id INTEGER PRIMARY KEY,
                site TEXT NOT NULL,
                name TEXT NOT NULL,
                steps_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        connection.commit()
    finally:
        connection.close()


@app.on_event("startup")
async def startup() -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
    init_db()


@app.get("/api/health")
async def health() -> dict[str, object]:
    """Report only local runtime state; dependency checks arrive in feature 2."""
    return {
        "ok": DB.exists() and BROWSER_PROFILE.is_dir(),
        "service": "hectiCat",
        "version": app.version,
        "database": str(DB),
        "browser_profile": str(BROWSER_PROFILE),
    }


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    return HTMLResponse(
        """<!doctype html>
        <html lang="en"><head><meta charset="utf-8"><title>hectiCat</title>
        <style>body{font:16px system-ui;margin:3rem;max-width:48rem}code{background:#f4f4f5;padding:.15rem .3rem;border-radius:.2rem}</style>
        </head><body><h1>hectiCat</h1>
        <p>Local runtime is ready. Resume, job, and application workflows will appear here as their features are implemented.</p>
        <p><a href="/api/health">View runtime health</a></p>
        <p>Dashboard is bound for local use at <code>127.0.0.1:8765</code>.</p>
        </body></html>"""
    )


init_db()
