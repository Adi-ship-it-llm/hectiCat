#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Unsupported OS: hectiCat targets macOS."
  exit 1
fi

if [[ "$(uname -m)" != "arm64" ]]; then
  echo "Unsupported CPU: hectiCat targets Apple Silicon (arm64)."
  exit 1
fi

python3 -c 'import fastapi, uvicorn' || {
  echo "Missing Python runtime packages. Run: python3 -m pip install -r $PROJECT_DIR/requirements.txt"
  exit 1
}

echo "Runtime prerequisites are ready. Start hectiCat with: $PROJECT_DIR/run.sh"
