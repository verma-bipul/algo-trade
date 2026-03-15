"""
Streamlit dashboard for monitoring crypto trading strategies.

Reads trade data from Google Sheets, fetches live BTC price from Alpaca.
Deploy on Streamlit Cloud — NOT on the Pi.
"""

import os
import time
import json
from datetime import datetime, timezone, timedelta

import streamlit as st
import pandas as pd
import gspread
from dotenv import load_dotenv
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoLatestQuoteRequest

load_dotenv()

SYMBOL = "BTC/USD"

st.set_page_config(page_title="Crypto Trader", layout="wide")


# --- Connections (cached) ---

@st.cache_resource
def get_alpaca_client():
    key = os.getenv("APCA_API_KEY_ID")
    secret = os.getenv("APCA_API_SECRET_KEY")
    if not key or not secret:
        st.error("Alpaca API keys not configured.")
        st.stop()
    return CryptoHistoricalDataClient(key, secret)


@st.cache_resource
def get_sheet():
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    if not sheet_id:
        st.error("GOOGLE_SHEET_ID not configured.")
        st.stop()

    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        gc = gspread.service_account_from_dict(json.loads(creds_json))
    else:
        gc = gspread.service_account(filename=os.getenv("GOOGLE_CREDS_FILE", "credentials.json"))
    return gc.open_by_key(sheet_id)


# --- Data fetching (cached with TTL) ---

@st.cache_data(ttl=30)
def get_btc_price():
    client = get_alpaca_client()
    quote = client.get_crypto_latest_quote(CryptoLatestQuoteRequest(symbol_or_symbols=SYMBOL))
    return float(quote[SYMBOL].ask_price)


@st.cache_data(ttl=30)
def get_sheet_data():
    sheet = get_sheet()
    strategies = sheet.worksheet("strategies").get_all_records()
    trades = sheet.worksheet("trades").get_all_records()
    heartbeats = sheet.worksheet("heartbeats").get_all_records()
    return strategies, trades, heartbeats


def compute_strategy_stats(strategy, trades, btc_price, heartbeats):
    """Compute cash, position, equity, P&L for one strategy."""
    sid = strategy["strategy_id"]
    initial_cash = float(strategy["initial_cash"])
    my_trades = [t for t in trades if t["strategy_id"] == sid]

    # Replay trades to get current state
    cash = initial_cash
    qty = 0.0
    avg_entry = 0.0

    for t in my_trades:
        t_qty = float(t["qty"])
        t_price = float(t["price"])
        if t["side"] == "BUY":
            cost = t_qty * t_price
            new_qty = qty + t_qty
            avg_entry = ((qty * avg_entry) + cost) / new_qty if new_qty > 0 else 0
            qty = new_qty
            cash -= cost
        elif t["side"] == "SELL":
            cash += t_qty * t_price
            qty = max(qty - t_qty, 0)
            if qty == 0:
                avg_entry = 0

    equity = cash + qty * btc_price
    total_pnl = equity - initial_cash
    pnl_pct = (total_pnl / initial_cash) * 100 if initial_cash > 0 else 0
    unrealized = qty * (btc_price - avg_entry) if qty > 0 else 0
    realized = total_pnl - unrealized

    # Heartbeat status
    hb = next((h for h in heartbeats if h["strategy_id"] == sid), None)
    online = False
    if hb and hb["last_seen"]:
        try:
            last_seen = datetime.fromisoformat(hb["last_seen"])
            online = (datetime.now(timezone.utc) - last_seen) < timedelta(minutes=10)
        except (ValueError, TypeError):
            pass

    return {
        "strategy_id": sid,
        "display_name": strategy["display_name"],
        "state": "HOLDING" if qty > 0 else "FLAT",
        "online": online,
        "last_seen": hb["last_seen"] if hb else "never",
        "qty": qty,
        "cash": round(cash, 2),
        "equity": round(equity, 2),
        "pnl": round(total_pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "trade_count": len(my_trades),
    }


# --- UI ---

st.title("Crypto Trader Dashboard")

try:
    btc_price = get_btc_price()
    strategies, trades, heartbeats = get_sheet_data()
except Exception as e:
    st.error(f"Failed to load data: {e}")
    st.stop()

st.metric("BTC/USD", f"${btc_price:,.2f}")

# Strategy cards
if strategies:
    cols = st.columns(len(strategies))

    for i, s in enumerate(strategies):
        stats = compute_strategy_stats(s, trades, btc_price, heartbeats)

        with cols[i]:
            status = "🟢 Online" if stats["online"] else "🔴 Offline"
            st.subheader(f"{stats['display_name']}")
            st.caption(f"{status} · Last seen: {stats['last_seen'][:19] if stats['last_seen'] != 'never' else 'never'}")

            st.metric("Equity", f"${stats['equity']:.2f}",
                       delta=f"${stats['pnl']:.2f} ({stats['pnl_pct']:.2f}%)")

            c1, c2 = st.columns(2)
            c1.metric("Cash", f"${stats['cash']:.2f}")
            c2.metric("BTC Held", f"{stats['qty']:.8f}")

            c3, c4 = st.columns(2)
            c3.metric("Trades", stats["trade_count"])
            c4.metric("State", stats["state"])

# Equity chart
st.subheader("Equity Over Time")
if trades:
    all_points = []
    for s in strategies:
        sid = s["strategy_id"]
        initial_cash = float(s["initial_cash"])
        my_trades = sorted(
            [t for t in trades if t["strategy_id"] == sid],
            key=lambda t: t["timestamp"],
        )

        cash = initial_cash
        qty = 0.0
        for t in my_trades:
            t_qty = float(t["qty"])
            t_price = float(t["price"])
            if t["side"] == "BUY":
                cash -= t_qty * t_price
                qty += t_qty
            else:
                cash += t_qty * t_price
                qty = max(qty - t_qty, 0)
            all_points.append({
                "time": t["timestamp"][:16],
                "equity": round(cash + qty * t_price, 2),
                "strategy": s["display_name"],
            })

        # Current point
        all_points.append({
            "time": "now",
            "equity": round(cash + qty * btc_price, 2),
            "strategy": s["display_name"],
        })

    df_chart = pd.DataFrame(all_points)
    if not df_chart.empty:
        st.line_chart(df_chart, x="time", y="equity", color="strategy")
else:
    st.info("No trades yet — chart will appear after the first trade.")

# Recent trades table
st.subheader("Recent Trades")
if trades:
    df_trades = pd.DataFrame(trades)
    df_trades["qty"] = df_trades["qty"].astype(float)
    df_trades["price"] = df_trades["price"].astype(float)
    df_trades["value"] = (df_trades["qty"] * df_trades["price"]).round(2)
    df_trades = df_trades.sort_values("timestamp", ascending=False).head(50)
    st.dataframe(
        df_trades[["timestamp", "strategy_id", "side", "symbol", "qty", "price", "value"]],
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No trades yet.")

# Auto-refresh
st.caption("Data refreshes every 30 seconds.")
time.sleep(30)
st.rerun()
