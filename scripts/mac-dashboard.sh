#!/usr/bin/env bash
# Run the gary dashboard locally on your Mac (http://localhost:8000).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PORT="${GARY_PORT:-8000}"
HOST="${GARY_HOST:-127.0.0.1}"
URL="http://${HOST}:${PORT}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This helper is for macOS. Use: .venv/bin/uvicorn gary.app:app --reload --host 0.0.0.0 --port ${PORT}" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Install Python 3 first: brew install python@3.12" >&2
  exit 1
fi

if [[ ! -x .venv/bin/uvicorn ]]; then
  echo "Setting up gary (.venv + dependencies)..."
  bash scripts/install.sh
fi

_server_up() {
  curl -sf "${URL}/api/health" >/dev/null 2>&1
}

if _server_up; then
  echo "gary is already running at ${URL}"
  open "$URL"
  exit 0
fi

echo "Starting gary at ${URL}"
(
  for _ in $(seq 1 60); do
    if _server_up; then
      open "$URL" 2>/dev/null || true
      exit 0
    fi
    sleep 0.25
  done
) &

exec .venv/bin/uvicorn gary.app:app --reload --host "$HOST" --port "$PORT"
