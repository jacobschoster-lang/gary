#!/usr/bin/env bash
# Provision the gary dev environment (venv + Python deps).
# Used by Cursor Cloud (.cursor/environment.json) and runnable locally.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found on PATH" >&2
  exit 1
fi

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

.venv/bin/python -c "import fastapi, uvicorn; print('gary deps ok')"
