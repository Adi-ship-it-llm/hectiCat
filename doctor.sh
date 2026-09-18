#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

OS_NAME="$(uname -s)"
case "$OS_NAME" in
  Darwin|Linux) ;;
  *)
    echo "Unsupported OS: $OS_NAME. Use doctor.bat on Windows."
    exit 1
    ;;
esac

echo "OS: $OS_NAME ($(uname -m))"

python3 -c 'import fastapi, httpx, uvicorn' || {
  echo "Missing Python runtime packages. Run: python3 -m pip install -r $PROJECT_DIR/requirements.txt"
  exit 1
}

echo "Runtime prerequisites are ready. Start hectiCat with: $PROJECT_DIR/run.sh"
echo
echo "Optional automation dependencies:"
if curl --silent --fail http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "- Ollama: available"
else
  echo "- Ollama: unavailable at http://127.0.0.1:11434"
fi

if command -v hermes >/dev/null 2>&1; then
  echo "- Hermes: $(command -v hermes)"
else
  echo "- Hermes: unavailable"
fi
