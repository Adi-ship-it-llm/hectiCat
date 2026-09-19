"""Local runtime foundation for hectiCat.

Later features add resume ingestion, job scoring, and browser automation.  This
module intentionally contains only the local server, durable schema, and a
minimal dashboard needed to operate those features safely.
"""

from __future__ import annotations

import html
import os
import shutil
import signal
import sqlite3
import subprocess
import time
from contextlib import asynccontextmanager

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse



BASE = Path(os.environ.get("HECTICAT_HOME", "~/hectiCat")).expanduser()
DB = BASE / "data" / "hecticat.sqlite3"
PROFILE_JSON = BASE / "profile.json"
RESUMES_DIR = BASE / "resumes"
BROWSER_PROFILE = BASE / "browser-profile"
LOG_DIR = BASE / "logs"
OLLAMA_LOG = LOG_DIR / "ollama.log"
MODEL = os.environ.get("HECTICAT_MODEL", "qwen3.5:9b")
OLLAMA = os.environ.get("HECTICAT_OLLAMA", "http://127.0.0.1:11434")



def resumes_dir() -> Path:
    """Return and ensure the directory used for storing uploaded resumes."""
    directory = BASE / "resumes"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def extract_text(path: Path) -> str:
    """Extract plain text from a PDF, DOCX, or TXT file."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages).strip()
    elif suffix == ".docx":
        from docx import Document

        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs).strip()
    elif suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="replace").strip()
    else:
        raise ValueError(f"Unsupported resume format: {suffix}")


def auto_import_resumes() -> int:
    """Scan the resumes directory for untracked files and import their text into the database."""
    rdir = resumes_dir()
    connection = db()
    imported = 0
    try:
        known = {r["filename"] for r in connection.execute("SELECT filename FROM resumes")}
        for item in sorted(rdir.glob("*")):
            if item.is_file() and item.suffix.lower() in (".pdf", ".docx", ".txt") and item.name not in known:
                try:
                    text = extract_text(item)
                    connection.execute(
                        "INSERT INTO resumes(name, filename, text, active, created_at) VALUES(?, ?, ?, 1, ?)",
                        (item.stem, item.name, text, now()),
                    )
                    imported += 1
                except Exception:
                    continue
        if imported:
            connection.commit()
    finally:
        connection.close()
    return imported


async def startup() -> None:
    """Initialize directories, durable schema, and auto-import resumes."""
    BASE.mkdir(parents=True, exist_ok=True)
    BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
    resumes_dir()
    init_db()
    auto_import_resumes()


@asynccontextmanager
async def lifespan(application: FastAPI):
    await startup()
    yield


app = FastAPI(title="hectiCat", version="0.1.0", lifespan=lifespan)



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


def check_result(ok: bool, label: str, detail: str) -> dict[str, object]:
    """Build a consistent health-check payload for API and dashboard use."""
    return {"ok": ok, "label": label, "detail": detail}


async def ollama_health() -> tuple[dict[str, object], dict[str, object]]:
    """Check local Ollama and whether the configured model is available."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{OLLAMA.rstrip('/')}/api/tags")
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        unavailable = check_result(False, "Unavailable", f"{type(exc).__name__}: {exc}")
        missing_model = check_result(False, MODEL, "Ollama is not reachable.")
        return unavailable, missing_model

    model_names = {
        str(item.get("name") or item.get("model"))
        for item in payload.get("models", [])
        if item.get("name") or item.get("model")
    }
    model_available = MODEL in model_names
    ollama = check_result(True, "Available", OLLAMA)
    model = check_result(
        model_available,
        MODEL,
        "Model is installed." if model_available else "Configured model is not installed in Ollama.",
    )
    return ollama, model


async def is_ollama_reachable() -> bool:
    """Return whether the configured Ollama server is responding."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{OLLAMA.rstrip('/')}/api/tags")
            response.raise_for_status()
            return True
    except httpx.HTTPError:
        return False


def start_ollama_process() -> dict[str, object]:
    """Start Ollama silently in the background if the binary is installed."""
    ollama_binary = shutil.which("ollama")
    if ollama_binary is None:
        return {
            "ok": False,
            "started": False,
            "message": "Ollama is not installed or not on PATH.",
        }

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = OLLAMA_LOG.open("ab")
    try:
        subprocess.Popen(
            [ollama_binary, "serve"],
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    finally:
        log.close()

    return {
        "ok": True,
        "started": True,
        "message": "Ollama start requested.",
        "log": str(OLLAMA_LOG),
    }


def render_check(name: str, check: dict[str, object]) -> str:
    """Render one dashboard health row."""
    css = "ok" if check["ok"] else "bad"
    label = html.escape(str(check["label"]))
    detail = html.escape(str(check["detail"]))
    return (
        f'<div class="health-check {css}">'
        f"<b>{html.escape(name)}</b>"
        f"<span>{label}</span>"
        f"<p>{detail}</p>"
        "</div>"
    )


@app.get("/api/health")
async def health() -> dict[str, object]:
    """Report local runtime and automation dependency checks."""
    ollama, model = await ollama_health()
    hermes_path = shutil.which("hermes")
    checks = {
        "database": check_result(DB.exists(), "Ready" if DB.exists() else "Missing", str(DB)),
        "browser_profile": check_result(
            BROWSER_PROFILE.is_dir(),
            "Ready" if BROWSER_PROFILE.is_dir() else "Missing",
            str(BROWSER_PROFILE),
        ),
        "ollama": ollama,
        "hermes": check_result(
            hermes_path is not None,
            "Available" if hermes_path else "Unavailable",
            hermes_path or "Install Hermes before browser automation features are enabled.",
        ),
        "model": model,
    }
    return {
        "ok": all(bool(check["ok"]) for check in checks.values()),
        "service": "hectiCat",
        "version": app.version,
        "model": MODEL,
        "ollama": OLLAMA,
        "database": str(DB),
        "browser_profile": str(BROWSER_PROFILE),
        "checks": checks,
    }


@app.post("/api/shutdown")
async def shutdown(background_tasks: BackgroundTasks) -> dict[str, object]:
    """Stop the local dashboard server from the browser UI."""
    background_tasks.add_task(stop_process_after_response)
    return {"ok": True, "message": "hectiCat dashboard is shutting down."}


@app.post("/api/ollama/start")
async def start_ollama() -> dict[str, object]:
    """Start the local Ollama server silently when it is not already running."""
    if await is_ollama_reachable():
        return {"ok": True, "started": False, "message": "Ollama is already running."}

    result = start_ollama_process()
    if not result["ok"]:
        return result

    for _ in range(20):
        if await is_ollama_reachable():
            result["ready"] = True
            result["message"] = "Ollama is running."
            return result
        time.sleep(0.25)

    result["ready"] = False
    result["message"] = "Ollama was started but is not responding yet."
    return result


@app.post("/resumes/upload")
async def resume_upload(request: Request, file: UploadFile = File(...)) -> Any:
    """Upload a resume (PDF, DOCX, or TXT), store it, extract its text, and persist in database."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")

    safe_name = Path(file.filename).name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in (".pdf", ".docx", ".txt"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported resume format '{suffix}'. Supported formats: .pdf, .docx, .txt",
        )

    rdir = resumes_dir()
    dest = rdir / safe_name
    content = await file.read()
    dest.write_bytes(content)

    try:
        text = extract_text(dest)
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=f"Failed to extract text from {safe_name}: {exc}",
        )

    connection = db()
    try:
        existing = connection.execute(
            "SELECT id FROM resumes WHERE filename = ?", (safe_name,)
        ).fetchone()
        if existing:
            connection.execute(
                "UPDATE resumes SET name = ?, text = ?, active = 1, created_at = ? WHERE id = ?",
                (dest.stem, text, now(), existing["id"]),
            )
            resume_id = existing["id"]
        else:
            cursor = connection.execute(
                "INSERT INTO resumes (name, filename, text, active, created_at) VALUES (?, ?, ?, 1, ?)",
                (dest.stem, safe_name, text, now()),
            )
            resume_id = cursor.lastrowid
        connection.commit()
    finally:
        connection.close()

    accept = request.headers.get("accept", "").lower()
    if "application/json" in accept:
        return JSONResponse(
            {
                "ok": True,
                "id": resume_id,
                "name": dest.stem,
                "filename": safe_name,
                "text_length": len(text),
            }
        )

    from urllib.parse import urlparse
    referer = request.headers.get("referer", "/") or "/"
    target_path = urlparse(referer).path
    if target_path not in ("/admin", "/"):
        target_path = "/"
    return RedirectResponse(target_path, status_code=303)



@app.get("/api/resumes")
async def api_list_resumes() -> list[dict[str, object]]:
    """Return all stored resumes in the library."""
    connection = db()
    try:
        rows = connection.execute(
            "SELECT id, name, filename, text, active, created_at FROM resumes ORDER BY id DESC"
        ).fetchall()
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "filename": row["filename"],
                "active": bool(row["active"]),
                "created_at": row["created_at"],
                "text_length": len(row["text"] or ""),
                "text_preview": (row["text"] or "")[:250],
            }
            for row in rows
        ]
    finally:
        connection.close()


@app.get("/api/resumes/{resume_id}")
async def api_get_resume(resume_id: int) -> dict[str, object]:
    """Return full details and extracted text for a specific resume."""
    connection = db()
    try:
        row = connection.execute(
            "SELECT id, name, filename, text, active, created_at FROM resumes WHERE id = ?",
            (resume_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Resume not found.")
        return {
            "id": row["id"],
            "name": row["name"],
            "filename": row["filename"],
            "text": row["text"],
            "active": bool(row["active"]),
            "created_at": row["created_at"],
        }
    finally:
        connection.close()


@app.get("/", response_class=HTMLResponse)
async def user_workspace() -> HTMLResponse:
    """User-facing workspace: job discovery, resume library, application pipeline."""
    health_state = await health()
    counts = dashboard_counts()
    system_ok = health_state["ok"]
    status_text = "System ready" if system_ok else "Needs attention"
    status_class = "good" if system_ok else "warn"

    connection = db()
    try:
        resumes = connection.execute(
            "SELECT id, name, filename, text, active, created_at FROM resumes ORDER BY id DESC"
        ).fetchall()
    finally:
        connection.close()

    if resumes:
        resume_rows = []
        for r in resumes:
            text_str = str(r["text"] or "")
            words = len(text_str.split())
            status_badge = (
                '<span class="badge active">Active</span>'
                if r["active"]
                else '<span class="badge inactive">Inactive</span>'
            )
            r_id = r["id"]
            r_name = html.escape(str(r["name"]))
            r_fname = html.escape(str(r["filename"]))
            r_text = html.escape(text_str)
            resume_rows.append(
                f"""<tr>
                  <td><b>{r_id}</b></td>
                  <td><strong>{r_name}</strong></td>
                  <td><code>{r_fname}</code></td>
                  <td>
                    <div style="font-size: 13px; color: var(--muted); margin-bottom: 4px;">{words} words</div>
                    <details class="preview-box">
                      <summary>View extracted text</summary>
                      <pre>{r_text}</pre>
                    </details>
                  </td>
                  <td>{status_badge}</td>
                </tr>"""
            )
        resume_table_html = f"""
        <div style="margin-top: 16px; overflow-x: auto;">
          <table class="data-table">
            <thead>
              <tr>
                <th style="width: 50px;">ID</th>
                <th>Name</th>
                <th>Filename</th>
                <th>Extracted Content</th>
                <th style="width: 80px;">Status</th>
              </tr>
            </thead>
            <tbody>
              {''.join(resume_rows)}
            </tbody>
          </table>
        </div>
        """
    else:
        resume_table_html = """
        <div class="empty">No resumes uploaded yet. Upload a PDF, DOCX, or TXT resume to get started.</div>
        """

    pipeline_stages = [
        ("Draft", counts["drafts"], "queue-item"),
        ("In Review", 0, "queue-item"),
        ("Filled", 0, "queue-item"),
        ("Approved", 0, "queue-item"),
        ("Submitted", counts["submitted"], "queue-item"),
    ]
    pipeline_html = "".join(
        f'<div class="{cls}"><b>{stage}</b><p>{cnt} applications</p></div>'
        for stage, cnt, cls in pipeline_stages
    )

    return HTMLResponse(
        f"""<!doctype html>
        <html lang="en">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>hectiCat — Workspace</title>
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
              padding: 32px 0 64px;
            }}
            header {{
              display: grid;
              grid-template-columns: 1fr auto;
              gap: 20px;
              align-items: end;
              padding: 0 0 28px;
              border-bottom: 2px solid var(--line);
            }}
            h1 {{ margin: 0; font-size: clamp(28px, 5vw, 52px); line-height: 1; }}
            h2 {{ margin: 0 0 8px; font-size: 17px; }}
            h3 {{ margin: 0 0 6px; font-size: 15px; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: .04em; }}
            p {{ margin: 0; color: var(--muted); }}
            code {{
              background: #efebe1; border: 1px solid var(--line); border-radius: 6px;
              color: #2d2b26; padding: 2px 6px;
            }}
            a {{ color: var(--accent); font-weight: 650; }}
            .tagline {{ font-size: 17px; color: var(--muted); margin-top: 6px; }}
            .status-badge {{
              display: inline-flex; align-items: center; gap: 8px;
              border: 1px solid var(--line); border-radius: 999px;
              padding: 8px 14px; background: var(--panel); font-weight: 700;
              text-decoration: none; color: var(--ink); font-size: 14px;
            }}
            .status-badge .dot {{
              width: 9px; height: 9px; border-radius: 50%; background: var(--accent);
            }}
            .status-badge.warn .dot {{ background: var(--warn); }}
            nav {{
              display: flex; gap: 12px; margin-top: 16px; flex-wrap: wrap;
            }}
            nav a {{
              font-size: 14px; color: var(--muted); text-decoration: none;
              border: 1px solid var(--line); border-radius: 999px;
              padding: 5px 14px; background: var(--panel); font-weight: 500;
              transition: border-color .15s;
            }}
            nav a:hover {{ border-color: var(--accent); color: var(--accent); }}
            .sections {{ display: grid; gap: 32px; margin-top: 36px; }}
            .section {{
              background: var(--panel); border: 1px solid var(--line);
              border-radius: 10px; padding: 22px 24px;
            }}
            .section-header {{
              display: flex; align-items: baseline; justify-content: space-between;
              flex-wrap: wrap; gap: 8px; margin-bottom: 12px;
            }}
            .coming-soon {{
              display: inline-block; font-size: 11px; font-weight: 700;
              padding: 2px 8px; border-radius: 999px;
              background: var(--warn-soft); color: var(--warn);
              border: 1px solid #edcf94; vertical-align: middle; margin-left: 8px;
            }}
            .url-form {{
              display: flex; gap: 10px; flex-wrap: wrap; margin-top: 14px;
              padding: 14px; background: #f9faf5; border: 1px solid var(--line);
              border-radius: 8px; align-items: center; opacity: .6; pointer-events: none;
            }}
            .url-form input[type="url"] {{
              flex: 1; min-width: 260px; padding: 8px 12px;
              border: 1px solid var(--line); border-radius: 7px;
              font-size: 14px; background: white;
            }}
            .button {{
              appearance: none; border: 1px solid var(--accent); border-radius: 7px;
              background: var(--accent); color: white; cursor: pointer;
              display: inline-flex; align-items: center; min-height: 36px;
              padding: 7px 14px; text-decoration: none; font-size: 14px; font-weight: 600;
            }}
            .button.secondary {{
              background: transparent; color: var(--accent);
            }}
            .upload-form {{
              display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
              margin-top: 14px; padding: 14px; background: #f9faf5;
              border: 1px solid var(--line); border-radius: 8px;
            }}
            .empty {{
              border: 1px dashed var(--line); border-radius: 8px;
              color: var(--muted); margin-top: 14px; padding: 14px;
            }}
            table.data-table {{
              width: 100%; border-collapse: collapse; font-size: 14px;
            }}
            table.data-table th, table.data-table td {{
              padding: 10px 12px; text-align: left;
              border-bottom: 1px solid var(--line); vertical-align: top;
            }}
            table.data-table th {{ background: #f0f2eb; font-weight: 650; }}
            table.data-table tr:hover td {{ background: #fafbf7; }}
            .badge {{
              display: inline-block; padding: 2px 8px; border-radius: 999px;
              font-size: 12px; font-weight: 700;
            }}
            .badge.active {{ background: var(--accent-soft); color: var(--accent); }}
            .badge.inactive {{ background: #e8e8e4; color: var(--muted); }}
            details.preview-box {{ margin-top: 4px; }}
            details.preview-box summary {{
              cursor: pointer; color: var(--accent); font-weight: 600; font-size: 13px;
            }}
            details.preview-box pre {{
              margin: 6px 0 0; padding: 8px 12px; background: #fafaf7;
              border: 1px solid var(--line); border-radius: 6px;
              font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
              font-size: 12px; white-space: pre-wrap; word-break: break-word;
              max-height: 180px; overflow-y: auto;
            }}
            .pipeline {{
              display: grid;
              grid-template-columns: repeat(5, 1fr);
              gap: 12px; margin-top: 14px;
            }}
            .queue-item {{
              border: 1px solid var(--line); border-radius: 8px;
              padding: 14px; background: #f9faf5;
            }}
            .queue-item b {{ display: block; margin-bottom: 4px; font-size: 14px; }}
            .queue-item p {{ font-size: 13px; }}
            .safety-list {{ margin: 12px 0 0; padding: 0 0 0 18px; color: var(--muted); }}
            .safety-list li {{ margin-bottom: 6px; font-size: 14px; }}
            @media (max-width: 780px) {{
              header {{ grid-template-columns: 1fr; }}
              .status-badge {{ justify-self: start; }}
              .pipeline {{ grid-template-columns: repeat(2, 1fr); }}
            }}
          </style>
        </head>
        <body>
          <main>
            <header>
              <div>
                <h1>hectiCat</h1>
                <p class="tagline">Your local job-application workspace. Everything stays on this Mac.</p>
                <nav>
                  <a href="#job-discovery">Job Leads</a>
                  <a href="#resume-library">Resumes</a>
                  <a href="#pipeline">Applications</a>
                  <a href="/admin">Admin ⚙️</a>
                </nav>
              </div>
              <a class="status-badge {status_class}" href="/admin" title="Click to open System Admin">
                <span class="dot"></span>
                <span>{status_text}</span>
              </a>
            </header>

            <div class="sections">

              <!-- ── Section 1: Job Discovery ── -->
              <section class="section" id="job-discovery">
                <div class="section-header">
                  <div>
                    <h2>Job Discovery <span class="coming-soon">Coming soon</span></h2>
                    <p>Paste a job listing URL and hectiCat will extract role details, score it against your resumes, and queue it for application.</p>
                  </div>
                </div>
                <div class="url-form" aria-disabled="true" title="Job Discovery is not yet available">
                  <input type="url" placeholder="https://jobs.example.com/posting/123" disabled>
                  <button class="button" type="button" disabled>Add Job Lead</button>
                </div>
                <p style="margin-top: 10px; font-size: 13px;">
                  {counts["tracked_jobs"]} job lead{"s" if counts["tracked_jobs"] != 1 else ""} tracked
                  &nbsp;·&nbsp;
                  {counts["drafts"]} draft{"s" if counts["drafts"] != 1 else ""}
                  &nbsp;·&nbsp;
                  {counts["submitted"]} submitted
                </p>
              </section>

              <!-- ── Section 2: Resume Library ── -->
              <section class="section" id="resume-library">
                <div class="section-header">
                  <div>
                    <h2>Resume Library</h2>
                    <p>Upload resume variants. hectiCat extracts and stores the full text locally for ATS matching and application drafting.</p>
                  </div>
                  <span style="color: var(--muted); font-size: 13px;">PDF · DOCX · TXT</span>
                </div>
                <form method="post" action="/resumes/upload" enctype="multipart/form-data" class="upload-form">
                  <label for="resume-upload" style="font-weight: 650;">Upload resume:</label>
                  <input type="file" id="resume-upload" name="file" accept=".pdf,.docx,.txt" required style="font-size: 14px;">
                  <button class="button" type="submit">Upload &amp; Extract Text</button>
                </form>
                {resume_table_html}
              </section>

              <!-- ── Section 3: Application Pipeline ── -->
              <section class="section" id="pipeline">
                <div class="section-header">
                  <div>
                    <h2>Application Pipeline</h2>
                    <p>Track every application as it moves from draft to submission.</p>
                  </div>
                </div>
                <div class="pipeline">
                  {pipeline_html}
                </div>
              </section>

              <!-- ── Section 4: Safety Assurance ── -->
              <section class="section" id="safety">
                <h2>Safety Assurance</h2>
                <p>hectiCat is designed to keep you in control and your data private.</p>
                <ul class="safety-list">
                  <li>🖥️ <strong>Local-only inference</strong> — all AI processing runs on your Mac via Ollama; no data leaves your machine.</li>
                  <li>🔒 <strong>Zero stored credentials</strong> — hectiCat never saves passwords or session cookies.</li>
                  <li>🛑 <strong>Protected-field stops</strong> — the browser agent pauses on sensitive fields and waits for your approval.</li>
                  <li>✅ <strong>Per-application approval hash</strong> — each submission requires a unique token you explicitly confirm.</li>
                </ul>
              </section>

            </div>
          </main>
        </body>
        </html>"""
    )


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard() -> HTMLResponse:
    health_state = await health()
    counts = dashboard_counts()
    status_text = "Ready" if health_state["ok"] else "Needs attention"
    status_class = "good" if health_state["ok"] else "warn"
    checks = health_state["checks"]
    health_checks = "\n".join(
        render_check(name, checks[name])
        for name in ("database", "browser_profile", "ollama", "hermes", "model")
    )
    resumes_dir_path = str(resumes_dir())

    connection = db()
    try:
        resumes = connection.execute(
            "SELECT id, name, filename, text, active, created_at FROM resumes ORDER BY id DESC"
        ).fetchall()
    finally:
        connection.close()

    if resumes:
        resume_rows = []
        for r in resumes:
            text_str = str(r["text"] or "")
            words = len(text_str.split())
            chars = len(text_str)
            status_badge = (
                '<span class="badge active">Active</span>'
                if r["active"]
                else '<span class="badge inactive">Inactive</span>'
            )
            r_id = r["id"]
            r_name = html.escape(str(r["name"]))
            r_fname = html.escape(str(r["filename"]))
            r_created = html.escape(str(r["created_at"]))
            r_text = html.escape(text_str)
            resume_rows.append(
                f"""<tr>
                  <td><b>{r_id}</b></td>
                  <td><strong>{r_name}</strong></td>
                  <td><code>{r_fname}</code></td>
                  <td>
                    <div style="font-size: 13px; color: var(--muted); margin-bottom: 4px;">{words} words ({chars} chars)</div>
                    <details class="preview-box">
                      <summary>View extracted text</summary>
                      <pre>{r_text}</pre>
                    </details>
                  </td>
                  <td>{status_badge}</td>
                  <td style="color: var(--muted); font-size: 13px;">{r_created}</td>
                </tr>"""
            )
        resume_table_html = f"""
        <div style="margin-top: 16px; overflow-x: auto;">
          <table class="data-table">
            <thead>
              <tr>
                <th style="width: 50px;">ID</th>
                <th>Name</th>
                <th>Filename</th>
                <th>Extracted Content</th>
                <th style="width: 80px;">Status</th>
                <th style="width: 170px;">Added</th>
              </tr>
            </thead>
            <tbody>
              {''.join(resume_rows)}
            </tbody>
          </table>
        </div>
        """
    else:
        resume_table_html = """
        <div class="empty">No resumes uploaded yet. Upload a PDF, DOCX, or TXT resume to start matching with job listings.</div>
        """

    return HTMLResponse(
        f"""<!doctype html>
        <html lang="en">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>hectiCat — System Admin</title>
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
            .health-grid {{
              display: grid;
              grid-template-columns: repeat(5, 1fr);
              gap: 12px;
              margin-top: 16px;
            }}
            .health-check {{
              border: 1px solid var(--line);
              border-radius: 8px;
              min-width: 0;
              padding: 12px;
              background: #f9faf5;
            }}
            .health-check b,
            .health-check span {{
              display: block;
            }}
            .health-check b {{
              font-size: 13px;
              color: var(--muted);
              margin-bottom: 4px;
            }}
            .health-check span {{
              color: var(--ink);
              font-weight: 750;
            }}
            .health-check p {{
              margin-top: 8px;
              overflow-wrap: anywhere;
              font-size: 13px;
            }}
            .health-check.ok {{
              background: var(--accent-soft);
              border-color: #b7d4c5;
            }}
            .health-check.bad {{
              background: var(--warn-soft);
              border-color: #edcf94;
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
            table.data-table {{
              width: 100%;
              border-collapse: collapse;
              margin-top: 14px;
              font-size: 14px;
            }}
            table.data-table th,
            table.data-table td {{
              padding: 10px 12px;
              text-align: left;
              border-bottom: 1px solid var(--line);
              vertical-align: top;
            }}
            table.data-table th {{
              background: #f0f2eb;
              font-weight: 650;
              color: var(--ink);
            }}
            table.data-table tr:hover td {{
              background: #fafbf7;
            }}
            .badge {{
              display: inline-block;
              padding: 2px 8px;
              border-radius: 999px;
              font-size: 12px;
              font-weight: 700;
            }}
            .badge.active {{
              background: var(--accent-soft);
              color: var(--accent);
            }}
            .badge.inactive {{
              background: #e8e8e4;
              color: var(--muted);
            }}
            details.preview-box {{
              margin-top: 4px;
            }}
            details.preview-box summary {{
              cursor: pointer;
              color: var(--accent);
              font-weight: 600;
              font-size: 13px;
            }}
            details.preview-box pre {{
              margin: 6px 0 0;
              padding: 8px 12px;
              background: #fafaf7;
              border: 1px solid var(--line);
              border-radius: 6px;
              font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
              font-size: 12px;
              white-space: pre-wrap;
              word-break: break-word;
              max-height: 180px;
              overflow-y: auto;
            }}
            @media (max-width: 780px) {{
              header, .metric-row, .health-grid {{ grid-template-columns: 1fr; }}
              .status {{ justify-self: start; }}
              .panel {{ grid-column: span 12; }}
            }}
          </style>
        </head>
        <body>
          <main>
            <header>
              <div>
                <a href="/" style="font-size: 13px; font-weight: 600; text-decoration: none; color: var(--muted); display: inline-flex; align-items: center; gap: 4px; margin-bottom: 10px;">← Workspace</a>
                <h1>hectiCat <span style="font-size: 20px; font-weight: 500; color: var(--muted);">System Admin</span></h1>
                <p>Runtime health, local services, and resume library management.</p>
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
                  <a class="button" href="/admin">Refresh</a>
                  <a class="button secondary" href="/api/health">Health</a>
                  <button class="button secondary" type="button" id="start-ollama">Start Ollama</button>
                  <button class="button danger" type="button" id="stop-dashboard">Stop dashboard</button>
                </div>
                <div class="toast" id="ollama-message">Ollama start requested. Refreshing health shortly.</div>
                <div class="toast" id="shutdown-message">hectiCat is shutting down. You can close this browser tab.</div>
              </div>

              <div class="panel wide">
                <h2>Local Health</h2>
                <p>These checks confirm whether the local app, browser automation layer, and configured AI model are ready for the job application workflow.</p>
                <div class="health-grid">
                  {health_checks}
                </div>
              </div>

              <div class="panel wide">
                <div style="display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 8px;">
                  <h2>Resume Library</h2>
                  <span style="color: var(--muted); font-size: 13px;">Supports PDF, DOCX, and TXT</span>
                </div>
                <p>Upload your resume variants. hectiCat extracts and persists the full text locally for ATS matching and application drafting.</p>

                <form method="post" action="/resumes/upload" enctype="multipart/form-data" style="margin-top: 16px; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; padding: 14px; background: #f9faf5; border: 1px solid var(--line); border-radius: 8px;">
                  <label for="resume-upload" style="font-weight: 650;">Upload resume:</label>
                  <input type="file" id="resume-upload" name="file" accept=".pdf,.docx,.txt" required style="font-size: 14px;">
                  <button class="button" type="submit">Upload &amp; Extract Text</button>
                </form>

                {resume_table_html}
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
                  <div class="path-item"><span>Resumes directory</span><code>{resumes_dir_path}</code></div>
                  <div class="path-item"><span>Browser profile</span><code>{health_state["browser_profile"]}</code></div>
                </div>
              </div>
            </section>
          </main>
          <script>
            const stopButton = document.getElementById("stop-dashboard");
            const startOllamaButton = document.getElementById("start-ollama");
            const shutdownMessage = document.getElementById("shutdown-message");
            const ollamaMessage = document.getElementById("ollama-message");

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

            startOllamaButton.addEventListener("click", async () => {{
              startOllamaButton.disabled = true;
              startOllamaButton.textContent = "Starting...";
              ollamaMessage.classList.add("show");
              try {{
                const response = await fetch("/api/ollama/start", {{ method: "POST" }});
                const result = await response.json();
                ollamaMessage.textContent = result.message || "Ollama start requested.";
              }} catch (error) {{
                ollamaMessage.textContent = "Could not request Ollama start.";
              }}
              window.setTimeout(() => window.location.reload(), 1500);
            }});
          </script>
        </body>
        </html>"""
    )


try:
    init_db()
except Exception:
    pass
