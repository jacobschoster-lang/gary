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

_ensure_venv() {
  python3 -m ensurepip --version >/dev/null 2>&1
}

if ! _ensure_venv; then
  if command -v apt-get >/dev/null 2>&1 && command -v sudo >/dev/null 2>&1; then
    PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "python${PY_VER}-venv" \
      || sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv
  fi
fi

if ! _ensure_venv; then
  echo "python3-venv is required (ensurepip missing)" >&2
  exit 1
fi

rm -rf .venv
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

.venv/bin/python -c "import fastapi, uvicorn; print('gary deps ok')"
