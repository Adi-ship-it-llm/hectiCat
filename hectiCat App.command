#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$PROJECT_DIR/.venv"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"
URL="http://127.0.0.1:8765"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/app.log"

cd "$PROJECT_DIR"
mkdir -p "$LOG_DIR"

echo "== hectiCat App =="

OS_NAME="$(uname -s)"
case "$OS_NAME" in
  Darwin) OPEN_CMD="open" ;;
  Linux) OPEN_CMD="$(command -v xdg-open || echo "")" ;;
  *)
    echo "Unsupported OS: $OS_NAME. Use 'hectiCat App.bat' on Windows."
    exit 1
    ;;
esac

if [[ ! -x "$PY" ]]; then
  echo "Creating local Python environment..."
  python3 -m venv "$VENV"
fi

echo "Installing app requirements..."
"$PIP" install --quiet --upgrade pip
"$PIP" install --quiet -r "$PROJECT_DIR/requirements.txt"

if curl --silent --fail "$URL/api/health" >/dev/null 2>&1; then
  echo "hectiCat is already running."
else
  echo "Starting hectiCat..."
  nohup "$PY" -m uvicorn app:app --host 127.0.0.1 --port 8765 >"$LOG_FILE" 2>&1 &
  SERVER_PID="$!"

  for _ in {1..40}; do
    if curl --silent --fail "$URL/api/health" >/dev/null 2>&1; then
      break
    fi
    if ! kill -0 "$SERVER_PID" >/dev/null 2>&1; then
      echo "hectiCat failed to start. See: $LOG_FILE"
      exit 1
    fi
    sleep 0.25
  done
fi

echo "Opening $URL"
if [[ -n "$OPEN_CMD" ]]; then
  "$OPEN_CMD" "$URL"
else
  echo "Open $URL in your browser."
fi

echo
echo "hectiCat is running locally. Use Stop dashboard in the app to quit the server."
