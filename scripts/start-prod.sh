#!/usr/bin/env bash
# Production server entrypoint (Render, Fly.io, Docker, etc.).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

mkdir -p "${GARY_FINANCE_FILE%/*}" "${GARY_CONTENT_FILE%/*}" "${GARY_PREVIEW_CACHE:-/tmp/gary_previews}"

exec python -m uvicorn gary.app:app --host "$HOST" --port "$PORT"
