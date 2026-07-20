#!/usr/bin/env bash
# Install gary as a macOS LaunchAgent (starts at login, restarts if it crashes).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
LABEL="com.gary.dashboard"
PLIST_DEST="$HOME/Library/LaunchAgents/${LABEL}.plist"
URL="http://127.0.0.1:8000"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This installer is for macOS only." >&2
  exit 1
fi

if [[ ! -x .venv/bin/uvicorn ]]; then
  echo "Setting up gary (.venv + dependencies)..."
  bash scripts/install.sh
fi

mkdir -p finance_data "$HOME/Library/LaunchAgents"
python3 - "$ROOT" <<'PY' >"$PLIST_DEST"
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
template = (root / "scripts/com.gary.dashboard.plist.template").read_text(encoding="utf-8")
print(template.replace("__GARY_ROOT__", str(root)))
PY

launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DEST"
launchctl enable "gui/$(id -u)/${LABEL}"
launchctl kickstart -k "gui/$(id -u)/${LABEL}"

for _ in $(seq 1 20); do
  if curl -sf "${URL}/api/health" >/dev/null 2>&1; then
    echo "gary dashboard is live at ${URL}"
    open "$URL" 2>/dev/null || true
    echo "Logs: ${ROOT}/finance_data/gary-dashboard.log"
    echo "Stop:  launchctl bootout gui/$(id -u)/${LABEL}"
    echo "Start: launchctl bootstrap gui/$(id -u) ${PLIST_DEST}"
    exit 0
  fi
  sleep 0.25
done

echo "Service installed but health check timed out. See ${ROOT}/finance_data/gary-dashboard.log" >&2
exit 1
