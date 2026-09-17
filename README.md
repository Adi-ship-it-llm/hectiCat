# hectiCat product documents

This package contains:

- `PRD.md` — product requirements, architecture-facing behavior, acceptance criteria, and roadmap.
- `TEST_PLAN.md` — P0 test matrix, negative tests, security tests, manual browser matrix, and release gates.
- `tests/test_hecticat.py` — deterministic tests for core hectiCat logic.
- `app.py` — local FastAPI runtime, GUI app, and durable SQLite schema foundation.
- `run.sh` — starts the app on `127.0.0.1:8765`.
- `doctor.sh` — checks the supported local runtime prerequisites.
- `hectiCat App.command` — one-click launcher for the local GUI app.
- `hectiCat Dashboard.command` — compatibility launcher that opens the same app.

## One-click launch the app

On macOS, double-click `hectiCat App.command`. It creates a local virtual
environment, installs the app dependencies, starts the server, and opens the
browser app. Use the app's **Stop dashboard** button to terminate the local
server from the GUI.

The local app opens at <http://127.0.0.1:8765>. By default, persistent local
data is stored in `~/hectiCat`; set `HECTICAT_HOME` to use a different data
directory.

## Run from terminal

```bash
python3 -m pip install -r requirements.txt
./doctor.sh
./run.sh
```

Run the automated suite from an installed hectiCat project:

```bash
cd ~/hectiCat
python -m pytest -q
```
