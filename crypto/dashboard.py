"""
Streamlit dashboard for monitoring crypto trading strategies.

Reads performance + trade data from Google Sheets.
Deploy on Streamlit Cloud — NOT on the Pi.

To add a new strategy: just add an entry to the STRATEGIES dict below.
"""

import os
import json

import streamlit as st
import pandas as pd
import gspread
from dotenv import load_dotenv

load_dotenv()

# --- Strategy registry ---
# To add a new strategy, add an entry here. The key must match the strategy_id
# used in portfolio.py on the Pi.

STRATEGIES = {
    "buy_and_hold": {
        "name": "BTC Buy & Hold",
        "description": "Buy $100 of BTC on day one, hold forever. Benchmark.",
    },
    "minute_momentum": {
        "name": "BTC 1-Min",
        "description": "Green 1-min candle → buy, hold 1 min, sell. Red → skip.",
    },
    "five_min_momentum": {
        "name": "BTC 5-Min",
        "description": "Green 5-min candle → buy, hold 5 min, sell. Red → skip.",
    },
    "thirty_min_momentum": {
        "name": "BTC 30-Min",
        "description": "Green 30-min candle → buy, hold 30 min, sell. Red → skip.",
    },
    "spy_rand5": {
        "name": "SPY Random 5-Min",
        "description": "Flip a coin every 5 min. Heads → buy, Tails → short. Close and repeat.",
    },
}

# --- Config ---

st.set_page_config(page_title="Algo Trader", layout="wide")


@st.cache_resource
def get_sheet():
    try:
        sheet_id = st.secrets["GOOGLE_SHEET_ID"]
    except (KeyError, FileNotFoundError):
        sheet_id = os.getenv("GOOGLE_SHEET_ID")

    if not sheet_id:
        st.error("GOOGLE_SHEET_ID not configured.")
        st.stop()

    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        gc = gspread.service_account_from_dict(creds_dict)
    except (KeyError, FileNotFoundError):
        gc = gspread.service_account(filename=os.getenv("GOOGLE_CREDS_FILE", "credentials.json"))

    return gc.open_by_key(sheet_id)


@st.cache_data(ttl=60)
def get_data():
    sheet = get_sheet()
    performance = sheet.worksheet("performance").get_all_records()
    trades = sheet.worksheet("trades").get_all_records()
    return performance, trades


# --- UI ---

st.title("Algo Trader")
st.caption("BTC/USD + SPY paper trading strategies — $100 budget each")

try:
    performance, trades = get_data()
except Exception as e:
    st.error(f"Failed to load data: {e}")
    st.stop()

perf_by_id = {r["strategy_id"]: r for r in performance}

strategy_list = list(STRATEGIES.items())
COLS_PER_ROW = 3

for row_start in range(0, len(strategy_list), COLS_PER_ROW):
    row_items = strategy_list[row_start:row_start + COLS_PER_ROW]
    cols = st.columns(COLS_PER_ROW)
    for i, (strategy_id, info) in enumerate(row_items):
        with cols[i]:
            st.subheader(info["name"])
            st.caption(info["description"])

            perf = perf_by_id.get(strategy_id)
            if perf:
                pnl = float(perf["pnl_dollar"])
                pnl_pct = float(perf["pnl_pct"])
                equity = float(perf["equity"])

                st.metric(
                    "Return",
                    f"${pnl:+.2f} ({pnl_pct:+.2f}%)",
                    delta=f"Equity: ${equity:.2f}",
                    delta_color="normal",
                )

                # Compact recent trades (last 5 only)
                my_trades = sorted(
                    [t for t in trades if t["strategy_id"] == strategy_id],
                    key=lambda x: x["timestamp"], reverse=True,
                )[:5]
                if my_trades:
                    st.caption("Recent trades:")
                    for t in my_trades:
                        st.text(f"  {t['side']} @ ${float(t['price']):,.2f}")

                st.caption(f"Updated: {str(perf['last_updated'])[:16]} UTC")
            else:
                st.info("Waiting for data...")

st.divider()
st.caption("Auto-refreshes every 60s.")
