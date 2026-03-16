#!/usr/bin/env bash
#
# Raspberry Pi setup script for crypto strategies
# Run from crypto/: bash deploy/setup.sh
#

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$REPO_DIR/.venv"
CURRENT_USER="$(whoami)"
SERVICES=("minute_momentum_inv" "spy_rand5" "random_tick_buy")

echo "=== Crypto Trader Pi Setup ==="
echo "Directory: $REPO_DIR"
echo "User: $CURRENT_USER"
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
    echo "   cp $REPO_DIR/.env.example $REPO_DIR/.env"
    echo "   nano $REPO_DIR/.env"
    echo ""
    echo "   Then re-run this script."
    exit 1
fi

# 3. Check for Google credentials
if [ ! -f "$REPO_DIR/credentials.json" ]; then
    echo ""
    echo "!! No credentials.json found."
    echo "   Download your Google service account JSON key and place it at:"
    echo "   $REPO_DIR/credentials.json"
    echo ""
    echo "   Then re-run this script."
    exit 1
fi

# 4. Install systemd services (fix user + paths for this machine)
echo ""
echo "Installing systemd services..."
for svc in "${SERVICES[@]}"; do
    # Replace User and paths to match this machine
    sed "s|User=.*|User=$CURRENT_USER|; s|WorkingDirectory=.*|WorkingDirectory=$REPO_DIR|; s|ExecStart=.*|ExecStart=$VENV_DIR/bin/python $REPO_DIR/${svc}.py|" \
        "$REPO_DIR/deploy/${svc}.service" | sudo tee /etc/systemd/system/${svc}.service > /dev/null
    echo "  Installed ${svc}.service"
done

sudo systemctl daemon-reload

# 5. Enable and start services
echo ""
echo "Enabling and starting services..."
for svc in "${SERVICES[@]}"; do
    sudo systemctl enable --now "${svc}.service"
    echo "  Started ${svc}.service"
done

# 6. Status
echo ""
echo "=== Service Status ==="
for svc in "${SERVICES[@]}"; do
    status=$(systemctl is-active "${svc}.service" 2>/dev/null || true)
    echo "  ${svc}: $status"
done

echo ""
echo "=== Setup Complete ==="
echo ""
echo "View logs:"
for svc in "${SERVICES[@]}"; do
    echo "  journalctl -u ${svc} -f"
done
echo ""
echo "Dashboard: deploy separately on Streamlit Cloud (see README)"
