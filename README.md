# hectiCat product documents

This package contains:

- `PRD.md` — product requirements, architecture-facing behavior, acceptance criteria, and roadmap.
- `TEST_PLAN.md` — P0 test matrix, negative tests, security tests, manual browser matrix, and release gates.
- `tests/test_hecticat.py` — deterministic tests for core hectiCat logic.

Run the automated suite from an installed hectiCat project:

```bash
cd ~/hectiCat
python -m pytest -q
```
