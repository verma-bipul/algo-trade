"""
Streamlit dashboard for monitoring crypto trading strategies.

Reads performance data from Google Sheets.
Deploy on Streamlit Cloud — NOT on the Pi.

To add a new strategy: just add an entry to the STRATEGIES dict below.
"""

import os
import json

import streamlit as st
import gspread
from dotenv import load_dotenv

load_dotenv()

# --- Strategy registry ---
# To add a new strategy, add an entry here. The key must match the strategy_id
# used in portfolio.py on the Pi.

STRATEGIES = {
    "buy_and_hold": {
        "name": "Buy & Hold",
        "description": (
            "Buy $100 of BTC on day one, hold forever. "
            "This is the benchmark — can any active strategy beat simply holding?"
        ),
    },
    "minute_momentum": {
        "name": "1-Min Momentum",
        "description": (
            "Every minute, check the last completed candle. "
            "Green candle (close > open) → buy BTC with all available cash. "
            "Hold for 1 minute, then sell. Red candle → skip. Repeat 24/7."
        ),
    },
    # Example — adding a future strategy:
    # "mean_reversion": {
    #     "name": "Mean Reversion",
    #     "description": "Buy when BTC drops 2% below its 1-hour moving average, sell when it reverts.",
    # },
}

# --- Config ---

st.set_page_config(page_title="Crypto Trader", layout="wide")


@st.cache_resource
def get_sheet():
    # Get sheet ID from Streamlit secrets or env var
    try:
        sheet_id = st.secrets["GOOGLE_SHEET_ID"]
    except (KeyError, FileNotFoundError):
        sheet_id = os.getenv("GOOGLE_SHEET_ID")

    if not sheet_id:
        st.error("GOOGLE_SHEET_ID not configured.")
        st.stop()

    # Get Google credentials: Streamlit secrets [gcp_service_account] table, or local file
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        gc = gspread.service_account_from_dict(creds_dict)
    except (KeyError, FileNotFoundError):
        gc = gspread.service_account(filename=os.getenv("GOOGLE_CREDS_FILE", "credentials.json"))

    return gc.open_by_key(sheet_id)


@st.cache_data(ttl=60)
def get_performance_data():
    sheet = get_sheet()
    return sheet.worksheet("performance").get_all_records()


# --- UI ---

st.title("Crypto Trader")
st.caption("BTC/USD paper trading strategies — updated every minute")

try:
    performance = get_performance_data()
except Exception as e:
    st.error(f"Failed to load data: {e}")
    st.stop()

# Build lookup: strategy_id -> performance row
perf_by_id = {r["strategy_id"]: r for r in performance}

# Render a card for each registered strategy
cols = st.columns(len(STRATEGIES))

for i, (strategy_id, info) in enumerate(STRATEGIES.items()):
    with cols[i]:
        st.subheader(info["name"])
        st.write(info["description"])

        st.divider()

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

            st.caption(f"Last updated: {str(perf['last_updated'])[:19]} UTC")
        else:
            st.info("Waiting for first data...")

# Footer
st.divider()
st.caption("Data refreshes every 60 seconds. Each strategy starts with a $100 virtual budget.")
