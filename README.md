# hectiCat product documents

This package contains:

- `PRD.md` — product requirements, architecture-facing behavior, acceptance criteria, and roadmap.
- `TEST_PLAN.md` — P0 test matrix, negative tests, security tests, manual browser matrix, and release gates.
- `tests/test_hecticat.py` — deterministic tests for core hectiCat logic.
- `app.py` — local FastAPI runtime and durable SQLite schema foundation.
- `run.sh` — starts the dashboard on `127.0.0.1:8765`.
- `doctor.sh` — checks the supported local runtime prerequisites.

## Run the local dashboard

```bash
python3 -m pip install -r requirements.txt
./doctor.sh
./run.sh
```

Open <http://127.0.0.1:8765>. By default, persistent local data is stored in
`~/hectiCat`; set `HECTICAT_HOME` to use a different data directory.

Run the automated suite from an installed hectiCat project:

```bash
cd ~/hectiCat
python -m pytest -q
```
