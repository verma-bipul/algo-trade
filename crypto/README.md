# Crypto Trading Strategies

BTC/USD paper trading via Alpaca. Strategies run 24/7 on a Raspberry Pi, trade data is logged to Google Sheets, and the dashboard runs on Streamlit Cloud.

## Architecture

```
Raspberry Pi                    Google Sheets              Streamlit Cloud
┌─────────────────┐   writes   ┌──────────────┐   reads   ┌───────────────┐
│ buy_and_hold.py  │──────────>│              │<──────────│               │
│ minute_momentum  │──────────>│  Trade Log   │           │   Dashboard   │
│                  │           │  Heartbeats  │           │               │
└─────────────────┘           └──────────────┘           └───────────────┘
        │                                                        │
        └──── trades via Alpaca API ─────────────────────────────┘
                                                          (reads BTC price)
```

## Strategies

| Strategy | Description | Budget |
|----------|-------------|--------|
| **Buy & Hold** | Buy $100 of BTC at startup, hold forever. Benchmark. | $100 |
| **1-Min Momentum** | Green 1-min candle → buy, hold 1 min, sell. Red → skip. | $100 |

## Setup

### 1. Google Cloud Service Account (one-time)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project (or use existing)
3. Enable the **Google Sheets API** (APIs & Services → Enable APIs)
4. Create a **Service Account** (IAM → Service Accounts → Create)
5. Create a key for it → download the JSON file
6. Save it as `credentials.json` in this directory

### 2. Google Sheet (one-time)

1. Create a new Google Sheet at [sheets.google.com](https://sheets.google.com)
2. Copy the Sheet ID from the URL: `https://docs.google.com/spreadsheets/d/SHEET_ID_HERE/edit`
3. Share the sheet with your service account email (found in credentials.json under `client_email`) — give it **Editor** access
4. The code auto-creates the needed tabs (trades, strategies, heartbeats) on first run

### 3. Raspberry Pi

```bash
git clone https://github.com/verma-bipul/algo-trade.git
cd algo-trade/crypto

# Configure
cp .env.example .env
nano .env              # Add: Alpaca keys + GOOGLE_SHEET_ID
# Copy credentials.json here

# Deploy
bash deploy/setup.sh
```

### 4. Streamlit Dashboard

1. Go to [share.streamlit.io](https://share.streamlit.io)
2. Connect your GitHub repo
3. Set main file: `crypto/dashboard.py`
4. Add secrets (Settings → Secrets):
   ```
   APCA_API_KEY_ID = "your_key"
   APCA_API_SECRET_KEY = "your_secret"
   GOOGLE_SHEET_ID = "your_sheet_id"
   GOOGLE_CREDENTIALS_JSON = '{"type":"service_account",...}'
   ```
5. Deploy

## Monitoring

The dashboard shows a green/red indicator for each strategy based on heartbeats. If a strategy hasn't sent a heartbeat in 10 minutes, it shows as offline.

To check on the Pi directly:
```bash
sudo systemctl status buy_and_hold
sudo systemctl status minute_momentum
journalctl -u minute_momentum -f   # live logs
```
