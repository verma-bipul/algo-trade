"""
Streamlit dashboard for monitoring trading strategies.

Reads performance + trade data from Google Sheets.
Deploy on Streamlit Cloud — NOT on the Pi.
"""

import os
import json

import streamlit as st
import pandas as pd
import gspread
from dotenv import load_dotenv

load_dotenv()

# --- Strategy registry ---

STRATEGIES = {
    "rsi2_qqq": {
        "name": "RSI-2 QQQ $1K",
        "description": "Buy QQQ when RSI(2) < 10, sell when > 50. Daily mean reversion.",
    },
    "lstm_portfolio": {
        "name": "LSTM Portfolio $10K",
        "description": "LSTM allocates $10K across VTI, SCHZ, PDBC, VIXM daily. AI-driven.",
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
st.caption("Algorithmic paper trading strategies")

try:
    performance, trades = get_data()
except Exception as e:
    st.error(f"Failed to load data: {e}")
    st.stop()

perf_by_id = {r["strategy_id"]: r for r in performance}

# Strategy cards
for strategy_id, info in STRATEGIES.items():
    st.subheader(info["name"])
    st.caption(info["description"])

    perf = perf_by_id.get(strategy_id)
    if perf:
        pnl = float(perf["pnl_dollar"])
        pnl_pct = float(perf["pnl_pct"])
        equity = float(perf["equity"])

        c1, c2, c3 = st.columns(3)
        c1.metric("Equity", f"${equity:,.2f}")
        c2.metric("P&L", f"${pnl:+,.2f}", delta=f"{pnl_pct:+.2f}%")
        c3.metric("Last Executed", str(perf["last_updated"])[:16] + " UTC")

        # Portfolio holdings (for LSTM — shows allocation from trade notes)
        my_trades = sorted(
            [t for t in trades if t["strategy_id"] == strategy_id],
            key=lambda x: x["timestamp"], reverse=True,
        )[:5]

        if my_trades:
            st.caption("Recent trades:")
            for t in my_trades:
                ts = str(t["timestamp"])[:16]
                side = t["side"]
                symbol = t["symbol"]
                price = t["price"]

                # LSTM logs allocation as order_id field
                if side == "REBALANCE":
                    st.text(f"  {ts} — REBALANCE (equity ${float(price):,.2f}) — {t.get('order_id', '')}")
                else:
                    st.text(f"  {ts} — {side} {symbol} @ ${float(price):,.2f}")
    else:
        st.info("Waiting for data...")

    st.divider()

st.caption("Auto-refreshes every 60s.")
