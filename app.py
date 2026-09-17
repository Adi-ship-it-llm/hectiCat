"""Local runtime foundation for hectiCat.

Later features add resume ingestion, job scoring, and browser automation.  This
module intentionally contains only the local server, durable schema, and a
minimal dashboard needed to operate those features safely.
"""

from __future__ import annotations

import os
import signal
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI
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


def dashboard_counts() -> dict[str, int]:
    """Return tracker counts for the local job application dashboard."""
    connection = db()
    try:
        row = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM resumes WHERE active = 1) AS active_resumes,
                (SELECT COUNT(*) FROM jobs) AS tracked_jobs,
                (SELECT COUNT(*) FROM applications WHERE status = 'draft') AS drafts,
                (SELECT COUNT(*) FROM applications WHERE status = 'submitted') AS submitted
            """
        ).fetchone()
        return {
            "active_resumes": int(row["active_resumes"]),
            "tracked_jobs": int(row["tracked_jobs"]),
            "drafts": int(row["drafts"]),
            "submitted": int(row["submitted"]),
        }
    finally:
        connection.close()


def stop_process_after_response() -> None:
    """Let the HTTP response finish before terminating the local server."""
    time.sleep(0.5)
    os.kill(os.getpid(), signal.SIGTERM)


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


@app.post("/api/shutdown")
async def shutdown(background_tasks: BackgroundTasks) -> dict[str, object]:
    """Stop the local dashboard server from the browser UI."""
    background_tasks.add_task(stop_process_after_response)
    return {"ok": True, "message": "hectiCat dashboard is shutting down."}


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    health_state = await health()
    counts = dashboard_counts()
    status_text = "Ready" if health_state["ok"] else "Needs attention"
    status_class = "good" if health_state["ok"] else "warn"
    return HTMLResponse(
        f"""<!doctype html>
        <html lang="en">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>hectiCat Dashboard</title>
          <style>
            :root {{
              color-scheme: light;
              --bg: #f6f7f4;
              --ink: #1b1b18;
              --muted: #66645d;
              --line: #d8ddd2;
              --panel: #fffffb;
              --accent: #27624d;
              --accent-soft: #e5f1eb;
              --danger: #8d2d26;
              --danger-soft: #f9e3df;
              --warn: #9a5a00;
              --warn-soft: #fff3d8;
            }}
            * {{ box-sizing: border-box; }}
            body {{
              margin: 0;
              background: var(--bg);
              color: var(--ink);
              font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            }}
            main {{
              width: min(1120px, calc(100vw - 32px));
              margin: 0 auto;
              padding: 32px 0 44px;
            }}
            header {{
              display: grid;
              grid-template-columns: 1fr auto;
              gap: 20px;
              align-items: end;
              padding: 0 0 24px;
              border-bottom: 1px solid var(--line);
            }}
            h1 {{
              margin: 0;
              font-size: clamp(32px, 5vw, 56px);
              line-height: 1;
              letter-spacing: 0;
            }}
            h2 {{
              margin: 0 0 10px;
              font-size: 18px;
            }}
            p {{ margin: 0; color: var(--muted); }}
            code {{
              background: #efebe1;
              border: 1px solid var(--line);
              border-radius: 6px;
              color: #2d2b26;
              padding: 2px 6px;
            }}
            a {{ color: var(--accent); font-weight: 650; }}
            .status {{
              justify-self: end;
              display: inline-flex;
              align-items: center;
              gap: 8px;
              border: 1px solid var(--line);
              border-radius: 999px;
              padding: 8px 12px;
              background: var(--panel);
              font-weight: 700;
            }}
            .dot {{
              width: 10px;
              height: 10px;
              border-radius: 50%;
              background: var(--accent);
            }}
            .status.warn .dot {{ background: var(--warn); }}
            .grid {{
              display: grid;
              grid-template-columns: repeat(12, 1fr);
              gap: 16px;
              margin-top: 24px;
            }}
            .panel {{
              grid-column: span 6;
              background: var(--panel);
              border: 1px solid var(--line);
              border-radius: 8px;
              padding: 18px;
              min-height: 160px;
            }}
            .wide {{ grid-column: span 12; }}
            .third {{ grid-column: span 4; }}
            .metric-row {{
              display: grid;
              grid-template-columns: repeat(4, 1fr);
              gap: 12px;
              margin-top: 16px;
            }}
            .metric {{
              border: 1px solid var(--line);
              border-radius: 8px;
              padding: 14px;
              background: #f9faf5;
            }}
            .metric strong {{
              display: block;
              font-size: 26px;
              line-height: 1.1;
            }}
            .path-list {{
              display: grid;
              gap: 10px;
              margin-top: 16px;
            }}
            .path-item {{
              display: grid;
              gap: 4px;
              min-width: 0;
            }}
            .path-item span {{
              color: var(--muted);
              font-size: 13px;
            }}
            .path-item code {{
              overflow-wrap: anywhere;
            }}
            .queue {{
              display: grid;
              gap: 12px;
              margin-top: 16px;
            }}
            .queue-item {{
              border: 1px solid var(--line);
              border-radius: 8px;
              padding: 14px;
              background: #f9faf5;
            }}
            .queue-item b {{ display: block; margin-bottom: 4px; }}
            .queue-item.active {{
              background: var(--accent-soft);
              border-color: #b7d4c5;
            }}
            .actions {{
              display: flex;
              flex-wrap: wrap;
              gap: 10px;
              margin-top: 18px;
            }}
            .button {{
              appearance: none;
              border: 1px solid var(--accent);
              border-radius: 7px;
              background: var(--accent);
              color: white;
              cursor: pointer;
              display: inline-flex;
              align-items: center;
              min-height: 38px;
              padding: 8px 12px;
              text-decoration: none;
            }}
            .button.secondary {{
              background: transparent;
              color: var(--accent);
            }}
            .button.danger {{
              background: var(--danger);
              border-color: var(--danger);
            }}
            .empty {{
              border: 1px dashed var(--line);
              border-radius: 8px;
              color: var(--muted);
              margin-top: 16px;
              padding: 14px;
            }}
            .toast {{
              display: none;
              margin-top: 14px;
              border: 1px solid #c9d8ce;
              border-radius: 8px;
              background: var(--accent-soft);
              color: #174432;
              padding: 12px;
            }}
            .toast.show {{ display: block; }}
            @media (max-width: 780px) {{
              header, .metric-row {{ grid-template-columns: 1fr; }}
              .status {{ justify-self: start; }}
              .panel {{ grid-column: span 12; }}
            }}
          </style>
        </head>
        <body>
          <main>
            <header>
              <div>
                <h1>hectiCat</h1>
                <p>Track job leads, resumes, application drafts, and submissions from this Mac.</p>
              </div>
              <div class="status {status_class}" aria-label="Runtime status">
                <span class="dot"></span>
                <span>{status_text}</span>
              </div>
            </header>

            <section class="grid" aria-label="Dashboard">
              <div class="panel wide">
                <h2>Application Tracker</h2>
                <p>Your local workspace for collecting job leads, matching them to resumes, drafting applications, and keeping submission status visible.</p>
                <div class="metric-row">
                  <div class="metric"><strong>{counts["tracked_jobs"]}</strong><p>Tracked jobs</p></div>
                  <div class="metric"><strong>{counts["active_resumes"]}</strong><p>Active resumes</p></div>
                  <div class="metric"><strong>{counts["drafts"]}</strong><p>Draft applications</p></div>
                  <div class="metric"><strong>{counts["submitted"]}</strong><p>Submitted</p></div>
                </div>
                <div class="actions">
                  <a class="button" href="http://127.0.0.1:8765">Refresh</a>
                  <a class="button secondary" href="/api/health">Health</a>
                  <button class="button danger" type="button" id="stop-dashboard">Stop dashboard</button>
                </div>
                <div class="toast" id="shutdown-message">hectiCat is shutting down. You can close this browser tab.</div>
              </div>

              <div class="panel">
                <h2>Application Pipeline</h2>
                <p>Use this as the command center for each job as the workflow features come online.</p>
                <div class="queue">
                  <div class="queue-item active"><b>Collect lead</b><p>Save a job URL and company details.</p></div>
                  <div class="queue-item"><b>Score fit</b><p>Compare requirements against your resumes.</p></div>
                  <div class="queue-item"><b>Draft application</b><p>Prepare forms and answers before submission.</p></div>
                  <div class="queue-item"><b>Submit and follow up</b><p>Track submitted applications and next actions.</p></div>
                </div>
              </div>

              <div class="panel">
                <h2>Recent Activity</h2>
                <p>Applications and job events will appear here as records are added.</p>
                <div class="empty">No jobs or applications have been tracked yet.</div>
                <div class="path-list">
                  <div class="path-item"><span>Local database</span><code>{health_state["database"]}</code></div>
                  <div class="path-item"><span>Browser profile</span><code>{health_state["browser_profile"]}</code></div>
                </div>
              </div>
            </section>
          </main>
          <script>
            const stopButton = document.getElementById("stop-dashboard");
            const shutdownMessage = document.getElementById("shutdown-message");

            stopButton.addEventListener("click", async () => {{
              stopButton.disabled = true;
              stopButton.textContent = "Stopping...";
              shutdownMessage.classList.add("show");
              try {{
                await fetch("/api/shutdown", {{ method: "POST" }});
              }} catch (error) {{
                shutdownMessage.textContent = "Shutdown request sent. You can close this browser tab.";
              }}
            }});
          </script>
        </body>
        </html>"""
    )


init_db()
