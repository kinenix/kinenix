#!/usr/bin/env bash
# ==============================================================================
# Kinenix Worker - install, update, or remove the systemd service (Linux)
#
#   ./kinenix-worker/scripts/install_service.sh              install or update, then start
#   ./kinenix-worker/scripts/install_service.sh --uninstall  stop and remove the service
#
# Run as the user that owns the Kinenix checkout (not as root); sudo is used where needed.
# The service runs `kinenix-worker daemon` as that user, starts at boot, and restarts on failure.
#
# With pip install "kinenix[worker]", run `kinenix-worker service install` instead; this script calls it.
#
# Per-user files (created if missing, never overwritten):
#   ~/.kinenix/worker.env      KINENIX_HUB_URL, KINENIX_HUB_API_KEY, KINENIX_WORKER_ID
#   ~/.kinenix/triggers.json   triggers for the daemon; empty means heartbeats only
# ==============================================================================
set -euo pipefail

SERVICE_NAME="kinenix-worker"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

if ! command -v systemctl >/dev/null 2>&1; then
    echo "ERROR: systemd (systemctl) not found. This script supports systemd-based Linux only." >&2
    exit 1
fi
if [ "$(id -u)" -eq 0 ]; then
    echo "ERROR: run this script as the user that owns the Kinenix checkout, not as root." >&2
    exit 1
fi

if [ "${1:-}" = "--uninstall" ]; then
    sudo systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
    sudo rm -f "$UNIT_PATH"
    sudo systemctl daemon-reload
    echo "Service '$SERVICE_NAME' removed. Files in ~/.kinenix were kept."
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
WORKER_BIN="$REPO_ROOT/.venv/bin/kinenix-worker"

if [ ! -x "$WORKER_BIN" ]; then
    echo "ERROR: $WORKER_BIN not found. Run kinenix-worker/scripts/setup_rpi.sh first." >&2
    exit 1
fi

# The same unit as `kinenix-worker service install` after a pip install (#153), run from the repository folder,
# so relative paths in triggers.json keep resolving against it
exec "$WORKER_BIN" service install --working-dir "$REPO_ROOT"
