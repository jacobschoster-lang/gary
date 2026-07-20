#!/usr/bin/env bash
# Install gary as a macOS LaunchAgent (starts at login, restarts if it crashes).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
LABEL="com.gary.dashboard"
PLIST_DEST="$HOME/Library/LaunchAgents/${LABEL}.plist"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This installer is for macOS only." >&2
  exit 1
fi

if [[ ! -x .venv/bin/uvicorn ]]; then
  echo "Setting up gary (.venv + dependencies)..."
  bash scripts/install.sh
fi

mkdir -p finance_data "$HOME/Library/LaunchAgents"
sed "s|__GARY_ROOT__|${ROOT}|g" scripts/com.gary.dashboard.plist.template > "$PLIST_DEST"

launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DEST"
launchctl enable "gui/$(id -u)/${LABEL}"
launchctl kickstart -k "gui/$(id -u)/${LABEL}"

echo "gary dashboard is live at http://localhost:8000"
echo "Logs: ${ROOT}/finance_data/gary-dashboard.log"
echo "Stop:  launchctl bootout gui/$(id -u)/${LABEL}"
echo "Start: launchctl bootstrap gui/$(id -u) ${PLIST_DEST}"
