---
name: crypto_system_architecture
description: Current state of the crypto trading system — strategies, data flow, and components
type: project
---

GitHub repo: https://github.com/verma-bipul/algo-trade (public)

Architecture:
- **Pi** (aether@100.105.164.8): runs 4 strategies as systemd services, writes to Google Sheets
- **Google Sheets**: stores trades (last 5 per strategy), state (cash/position), performance (equity/P&L), heartbeats
- **Streamlit Cloud**: dashboard reads from Google Sheets, no connection to Pi needed

4 strategies (each with $100 virtual budget, all BTC/USD):
1. `buy_and_hold` — buy once, hold forever (benchmark)
2. `minute_momentum` — 1-min candle momentum
3. `five_min_momentum` — 5-min candle momentum
4. `thirty_min_momentum` — 30-min candle momentum

Key files:
- `crypto/config.py` — Alpaca clients + Google Sheets setup
- `crypto/portfolio.py` — PortfolioTracker class (state tab for persistence, rolling 5-trade window)
- `crypto/dashboard.py` — Streamlit app with STRATEGIES dict registry
- `crypto/deploy/setup.sh` — auto-detects username/paths, installs all services

Google Sheets tabs: trades, strategies, state, heartbeats, performance

**How to apply:** When adding new strategies, follow the pattern: create script, add service file, add to setup.sh SERVICES array, add to dashboard STRATEGIES dict.
