#!/usr/bin/env bash
# Run the gary dashboard locally on your Mac (http://localhost:8000).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PORT="${GARY_PORT:-8000}"
HOST="${GARY_HOST:-127.0.0.1}"

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

if ! curl -sf "http://${HOST}:${PORT}/api/health" >/dev/null 2>&1; then
  :
else
  echo "gary is already running at http://${HOST}:${PORT}"
  open "http://${HOST}:${PORT}"
  exit 0
fi

echo "Starting gary at http://${HOST}:${PORT}"
open "http://${HOST}:${PORT}" 2>/dev/null || true
exec .venv/bin/uvicorn gary.app:app --reload --host "$HOST" --port "$PORT"
