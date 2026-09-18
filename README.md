# hectiCat product documents

This package contains:

- `PRD.md` — product requirements, architecture-facing behavior, acceptance criteria, and roadmap.
- `TEST_PLAN.md` — P0 test matrix, negative tests, security tests, manual browser matrix, and release gates.
- `tests/test_hecticat.py` — deterministic tests for core hectiCat logic.
- `app.py` — local FastAPI runtime, GUI app, and durable SQLite schema foundation.
- `run.sh` — starts the app on `127.0.0.1:8765`.
- `doctor.sh` — checks the supported local runtime prerequisites and reports optional automation dependencies.
- `hectiCat App.command` / `hectiCat App.bat` — one-click launcher for the local GUI app (macOS/Linux and Windows).
- `hectiCat Dashboard.command` / `hectiCat Dashboard.bat` — compatibility launcher that opens the same app.

hectiCat runs on macOS, Linux, and Windows. It needs Python 3.11+ and `curl`
on PATH (both ship by default on macOS, most Linux distros, and Windows 10/11).

## One-click launch the app

- **macOS/Linux:** double-click (or run) `hectiCat App.command`.
- **Windows:** double-click `hectiCat App.bat`.

Either one creates a local virtual environment, installs the app
dependencies, starts the server, and opens the browser app. Use the app's
**Stop dashboard** button to terminate the local server from the GUI.

The local app opens at <http://127.0.0.1:8765>. By default, persistent local
data is stored under the current user's home directory in `hectiCat` (e.g.
`~/hectiCat` on macOS/Linux, `%USERPROFILE%\hectiCat` on Windows); set
`HECTICAT_HOME` to use a different data directory.

The app's health panel reports the SQLite database, browser profile, Ollama,
Hermes, and configured model. Set `HECTICAT_MODEL` to use a model other than
`qwen3.5:9b`, and set `HECTICAT_OLLAMA` if Ollama is not running at
`http://127.0.0.1:11434`. Use **Start Ollama** in the app, or call
`POST /api/ollama/start`, to silently start `ollama serve` when the Ollama
binary is installed. Hermes detection (`shutil.which("hermes")`) works on any
platform where the `hermes` binary is on `PATH` — Nous Research ships
installers for macOS/Linux (`install.sh`) and Windows (`install.ps1`)
separately; hectiCat itself does not automate that install outside the
legacy `installer/hectiCat-OneClick.command` (macOS/Homebrew only). Browser
automation (Playwright-based job scraping/form-filling) is not yet part of
the shipped `app.py`; it exists only as a prototype inside that legacy
installer.

## Run from terminal

macOS/Linux:

```bash
python3 -m pip install -r requirements.txt
./doctor.sh
./run.sh
```

Windows (PowerShell or cmd):

```bash
python -m pip install -r requirements.txt
doctor.bat
run.bat
```

Run the automated suite from an installed hectiCat project:

```bash
cd ~/hectiCat
python -m pytest -q
```
