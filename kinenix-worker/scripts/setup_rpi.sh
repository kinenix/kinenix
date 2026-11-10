#!/usr/bin/env bash
# ==============================================================================
# Kinenix Worker - Automated Setup Script for Raspberry Pi 4 Model B (Linux ARM64)
# ==============================================================================
#
#   ./kinenix-worker/scripts/setup_rpi.sh               install and start the kinenix-worker service
#   ./kinenix-worker/scripts/setup_rpi.sh --no-service  install only, without the systemd service
# ==============================================================================
set -e

INSTALL_SERVICE=1
if [ "${1:-}" = "--no-service" ]; then
    INSTALL_SERVICE=0
fi

echo "=== Kinenix Worker Setup for Raspberry Pi 4 (ARM64) ==="
echo "Date: $(date)"
echo "Host: $(hostname)"
echo "Arch: $(uname -m)"

# 1. Architecture Check
ARCH=$(uname -m)
if [ "$ARCH" != "aarch64" ] && [ "$ARCH" != "arm64" ]; then
    echo "WARNING: Detected architecture '$ARCH'. Recommended is 64-bit ARM (aarch64/arm64)."
    echo "Proceeding anyway..."
fi

# 2. Install System Dependencies via apt
echo ""
echo "--> Step 1/6: Installing system packages and Playwright dependencies..."
sudo apt-get update -y
sudo apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    git \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libxshmfence1 \
    libglib2.0-0

# 3. Create & Activate Python Virtual Environment
echo ""
echo "--> Step 2/6: Setting up Python virtual environment (.venv)..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

source .venv/bin/activate
pip install --upgrade pip

# 4. Install kinenix-core and kinenix-worker in editable mode
echo ""
echo "--> Step 3/6: Installing kinenix-core and kinenix-worker packages..."
pip install -e kinenix-core
pip install -e kinenix-worker

# 5. Install Playwright Chromium Browser
echo ""
echo "--> Step 4/6: Installing Playwright Chromium browser for ARM64..."
python -m playwright install chromium

# 6. Verify Installation
echo ""
echo "--> Step 5/6: Verifying Worker installation..."
kinenix-worker info

# 7. Install the systemd service so the worker runs in the background and starts at boot
echo ""
if [ "$INSTALL_SERVICE" = "1" ]; then
    echo "--> Step 6/6: Installing the kinenix-worker systemd service..."
    "$SCRIPT_DIR/install_service.sh"
else
    echo "--> Step 6/6: Skipped the systemd service (--no-service)."
    echo "    Install it later with: $SCRIPT_DIR/install_service.sh"
fi

echo ""
echo "=============================================================================="
echo "Kinenix Worker successfully installed and verified on this device!"
echo ""
echo "Connect it to the Hub: edit ~/.kinenix/worker.env, then"
echo "    sudo systemctl restart kinenix-worker"
echo ""
echo "To activate the environment in the future, run:"
echo "    source .venv/bin/activate"
echo ""
echo "To run an example, run:"
echo "    kinenix init demo --example hello && kinenix-worker run demo"
echo "=============================================================================="
