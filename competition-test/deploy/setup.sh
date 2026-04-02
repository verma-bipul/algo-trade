#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$REPO_DIR/.venv"
CURRENT_USER="$(whoami)"
SERVICES=("lstm_strategy" "rsi2_qqq" "sma10_spy")

echo "=== UMN Algo Team 4 — Setup ==="
echo "Directory: $REPO_DIR"
echo "User: $CURRENT_USER"

# Venv
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

echo "Installing dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$REPO_DIR/requirements.txt"

# Check .env
if [ ! -f "$REPO_DIR/.env" ]; then
    echo "!! No .env file. Copy and fill in:"
    echo "   cp $REPO_DIR/.env.example $REPO_DIR/.env"
    exit 1
fi

# Install services
echo ""
echo "Installing services..."
for svc in "${SERVICES[@]}"; do
    sed "s|User=.*|User=$CURRENT_USER|; s|WorkingDirectory=.*|WorkingDirectory=$REPO_DIR|; s|ExecStart=.*|ExecStart=$VENV_DIR/bin/python $REPO_DIR/${svc}.py|" \
        "$REPO_DIR/deploy/${svc}.service" | sudo tee /etc/systemd/system/${svc}.service > /dev/null
    echo "  Installed ${svc}.service"
done

sudo systemctl daemon-reload

echo ""
echo "Enabling and starting..."
for svc in "${SERVICES[@]}"; do
    sudo systemctl enable --now "${svc}.service"
    echo "  Started ${svc}.service"
done

echo ""
echo "=== Status ==="
for svc in "${SERVICES[@]}"; do
    status=$(systemctl is-active "${svc}.service" 2>/dev/null || true)
    echo "  ${svc}: $status"
done

echo ""
echo "=== Done ==="
echo "View logs:"
for svc in "${SERVICES[@]}"; do
    echo "  journalctl -u ${svc} -f"
done
