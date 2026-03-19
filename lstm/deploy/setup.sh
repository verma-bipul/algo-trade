#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$REPO_DIR/.venv"
CURRENT_USER="$(whoami)"

echo "=== LSTM Portfolio Setup ==="
echo "Directory: $REPO_DIR"

# 1. Venv
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

echo "Installing dependencies (this may take a few minutes for PyTorch)..."
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$REPO_DIR/requirements.txt"

# 2. Check .env
if [ ! -f "$REPO_DIR/.env" ]; then
    echo "!! No .env file found. Copy from crypto or create one:"
    echo "   cp $REPO_DIR/.env.example $REPO_DIR/.env"
    exit 1
fi

# 3. Check credentials.json (try crypto folder too)
if [ ! -f "$REPO_DIR/credentials.json" ]; then
    CRYPTO_CREDS="$REPO_DIR/../crypto/credentials.json"
    if [ -f "$CRYPTO_CREDS" ]; then
        ln -sf "$CRYPTO_CREDS" "$REPO_DIR/credentials.json"
        echo "Linked credentials.json from crypto/"
    else
        echo "!! No credentials.json found."
        exit 1
    fi
fi

# 4. Install service
sed "s|User=.*|User=$CURRENT_USER|; s|WorkingDirectory=.*|WorkingDirectory=$REPO_DIR|; s|ExecStart=.*|ExecStart=$VENV_DIR/bin/python $REPO_DIR/lstm_deploy.py|" \
    "$REPO_DIR/deploy/lstm_portfolio.service" | sudo tee /etc/systemd/system/lstm_portfolio.service > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable --now lstm_portfolio.service

echo ""
echo "=== Status ==="
systemctl is-active lstm_portfolio.service || true
echo ""
echo "View logs: journalctl -u lstm_portfolio -f"
echo "Test now:  $VENV_DIR/bin/python $REPO_DIR/lstm_deploy.py --now"
