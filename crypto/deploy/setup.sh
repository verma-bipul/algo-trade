#!/usr/bin/env bash
#
# Raspberry Pi setup script for crypto strategies
# Run from crypto/: bash deploy/setup.sh
#

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$REPO_DIR/.venv"
SERVICES=("buy_and_hold" "minute_momentum" "dashboard")

echo "=== Crypto Trader Setup ==="
echo "Repo: $REPO_DIR"
echo ""

# 1. Create virtual environment
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
else
    echo "Virtual environment already exists."
fi

echo "Installing dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$REPO_DIR/requirements.txt"

# 2. Check for .env
if [ ! -f "$REPO_DIR/.env" ]; then
    echo ""
    echo "!! No .env file found."
    echo "   Copy the example and fill in your API keys:"
    echo ""
    echo "   cp $REPO_DIR/.env.example $REPO_DIR/.env"
    echo "   nano $REPO_DIR/.env"
    echo ""
    echo "   Then re-run this script."
    exit 1
fi

# 3. Install systemd services
echo ""
echo "Installing systemd services..."
for svc in "${SERVICES[@]}"; do
    sudo cp "$REPO_DIR/deploy/${svc}.service" /etc/systemd/system/
    echo "  Installed ${svc}.service"
done

sudo systemctl daemon-reload

# 4. Enable and start services
echo ""
echo "Enabling and starting services..."
for svc in "${SERVICES[@]}"; do
    sudo systemctl enable --now "${svc}.service"
    echo "  Started ${svc}.service"
done

# 5. Status
echo ""
echo "=== Service Status ==="
for svc in "${SERVICES[@]}"; do
    status=$(systemctl is-active "${svc}.service" 2>/dev/null || true)
    echo "  ${svc}: $status"
done

# 6. Dashboard URL
IP=$(hostname -I | awk '{print $1}')
echo ""
echo "=== Setup Complete ==="
echo "Dashboard: http://${IP}:5000"
echo ""
echo "View logs:"
echo "  journalctl -u buy_and_hold -f"
echo "  journalctl -u minute_momentum -f"
echo "  journalctl -u dashboard -f"
