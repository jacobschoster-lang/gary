#!/usr/bin/env bash
# Provision the gary dev environment (venv + Python deps).
# Used by Cursor Cloud (.cursor/environment.json) and runnable locally.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
STAMP=".venv/.deps_stamp"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found on PATH" >&2
  exit 1
fi

_ensure_venv() {
  python3 -m ensurepip --version >/dev/null 2>&1
}

if ! _ensure_venv; then
  PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  if command -v brew >/dev/null 2>&1; then
    brew install "python@${PY_VER}" 2>/dev/null || brew install python@3.12 2>/dev/null || true
  elif command -v apt-get >/dev/null 2>&1 && command -v sudo >/dev/null 2>&1; then
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "python${PY_VER}-venv" \
      || sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv
  fi
fi

if ! _ensure_venv; then
  echo "python3-venv is required (ensurepip missing)" >&2
  exit 1
fi

if [[ -d .venv ]] && ! .venv/bin/python -c "import sys" >/dev/null 2>&1; then
  rm -rf .venv
fi

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi

if [[ ! -f "$STAMP" ]] || [[ requirements.txt -nt "$STAMP" ]]; then
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
  touch "$STAMP"
fi

.venv/bin/python -c "import fastapi, uvicorn; print('gary deps ok')"
