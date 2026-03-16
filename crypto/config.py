"""
Shared configuration: Alpaca clients, Google Sheets, logging.
"""

import os
import json
import logging
from dotenv import load_dotenv
import gspread
from alpaca.trading.client import TradingClient
from alpaca.data.historical import CryptoHistoricalDataClient, StockHistoricalDataClient

load_dotenv()

# --- Alpaca ---
API_KEY = os.getenv("APCA_API_KEY_ID")
API_SECRET = os.getenv("APCA_API_SECRET_KEY")
TRADING_ENV = os.getenv("TRADING_ENV", "paper")

if not API_KEY or not API_SECRET:
    raise RuntimeError("APCA_API_KEY_ID and APCA_API_SECRET_KEY must be set in .env")

trading_client = TradingClient(API_KEY, API_SECRET, paper=(TRADING_ENV != "live"))
crypto_data_client = CryptoHistoricalDataClient(API_KEY, API_SECRET)
stock_data_client = StockHistoricalDataClient(API_KEY, API_SECRET)

# --- Google Sheets ---
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
if not GOOGLE_SHEET_ID:
    raise RuntimeError("GOOGLE_SHEET_ID must be set in .env")


def get_gsheet():
    """Connect to Google Sheet. Supports both credential file (Pi) and env var (Streamlit Cloud)."""
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        gc = gspread.service_account_from_dict(json.loads(creds_json))
    else:
        gc = gspread.service_account(filename=os.getenv("GOOGLE_CREDS_FILE", "credentials.json"))
    sheet = gc.open_by_key(GOOGLE_SHEET_ID)
    _ensure_worksheets(sheet)
    return sheet


def _ensure_worksheets(sheet):
    """Create required worksheet tabs if they don't exist."""
    existing = [ws.title for ws in sheet.worksheets()]

    if "trades" not in existing:
        ws = sheet.add_worksheet("trades", rows=1000, cols=7)
        ws.append_row(["timestamp", "strategy_id", "symbol", "side", "qty", "price", "order_id"])

    if "strategies" not in existing:
        ws = sheet.add_worksheet("strategies", rows=10, cols=4)
        ws.append_row(["strategy_id", "display_name", "initial_cash", "created_at"])

    if "heartbeats" not in existing:
        ws = sheet.add_worksheet("heartbeats", rows=10, cols=3)
        ws.append_row(["strategy_id", "last_seen", "status"])

    if "state" not in existing:
        ws = sheet.add_worksheet("state", rows=10, cols=4)
        ws.append_row(["strategy_id", "cash", "qty", "avg_entry_price", "held_symbol"])

    if "performance" not in existing:
        ws = sheet.add_worksheet("performance", rows=10, cols=8)
        ws.append_row(["strategy_id", "last_updated", "equity", "cash", "qty", "price", "pnl_dollar", "pnl_pct"])

    # Remove default Sheet1 if our sheets were just created
    if "Sheet1" in existing and len(existing) > 1:
        try:
            sheet.del_worksheet(sheet.worksheet("Sheet1"))
        except Exception:
            pass


# --- Logging ---
def get_logger(name: str) -> logging.Logger:
    """Return a logger that writes to both console and a log file."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    fh = logging.FileHandler(f"{name}.log")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger
