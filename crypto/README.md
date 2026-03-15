# Crypto Trader

Automated BTC/USD paper trading on Alpaca, designed to run 24/7 on a Raspberry Pi.

## Strategies

| Strategy | Description | Budget |
|----------|-------------|--------|
| **Buy & Hold** | Buy $100 of BTC at startup, hold forever. Benchmark baseline. | $100 |
| **1-Min Momentum** | Every minute: green candle → buy, hold 1 min, sell. Red → skip. | $100 |

Both strategies share one Alpaca paper account ($100k) but each tracks its own $100 virtual budget via SQLite.

## Quick Start

```bash
# Clone
git clone <your-repo-url> crypto-trader
cd crypto-trader

# Setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your Alpaca API keys

# Run strategies
python buy_and_hold.py      # Terminal 1
python minute_momentum.py   # Terminal 2
python dashboard.py         # Terminal 3 → http://localhost:5000
```

## Raspberry Pi Deployment

```bash
# On your Pi, clone the repo then:
bash deploy/setup.sh
```

This creates a venv, installs deps, and sets up systemd services so everything runs on boot.

### Manage Services

```bash
# Check status
sudo systemctl status buy_and_hold
sudo systemctl status minute_momentum
sudo systemctl status dashboard

# View logs
journalctl -u minute_momentum -f

# Stop/start
sudo systemctl stop minute_momentum
sudo systemctl start minute_momentum
```

## Dashboard

Flask web dashboard on port 5000 showing:
- Per-strategy equity, P&L, position state
- Equity comparison chart (Buy & Hold vs Momentum)
- Recent trades table

Auto-refreshes every 60 seconds.

## Project Structure

```
config.py              # Shared Alpaca clients + logging
portfolio.py           # SQLite portfolio tracker (per-strategy budgets)
buy_and_hold.py        # Strategy 1
minute_momentum.py     # Strategy 2
dashboard.py           # Flask dashboard
templates/
  dashboard.html       # Dashboard template (Bootstrap 5 + Chart.js)
deploy/
  *.service            # systemd unit files
  setup.sh             # Pi setup script
```

## Requirements

- Python 3.10+
- Alpaca paper trading account (free at [alpaca.markets](https://alpaca.markets))
- Raspberry Pi (or any Linux box) for 24/7 operation
