#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
exec python3 -m uvicorn app:app --host 127.0.0.1 --port 8765 --reload
