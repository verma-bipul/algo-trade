"""
Flask dashboard for monitoring crypto trading strategies.

Shows per-strategy stats, equity comparison chart, and recent trades.
Auto-refreshes every 60 seconds.
"""

import time
import sqlite3
from functools import lru_cache

from flask import Flask, render_template, jsonify
from alpaca.data.requests import CryptoLatestQuoteRequest

from config import crypto_data_client, DB_PATH, get_logger

app = Flask(__name__)
logger = get_logger("dashboard")

SYMBOL = "BTC/USD"

# Price cache (avoid hammering Alpaca on every request)
_price_cache = {"price": 0.0, "timestamp": 0}
CACHE_TTL = 30  # seconds


def get_btc_price() -> float:
    """Get BTC price with 30s cache."""
    now = time.time()
    if now - _price_cache["timestamp"] < CACHE_TTL and _price_cache["price"] > 0:
        return _price_cache["price"]

    try:
        quote = crypto_data_client.get_crypto_latest_quote(
            CryptoLatestQuoteRequest(symbol_or_symbols=SYMBOL)
        )
        price = float(quote[SYMBOL].ask_price)
        _price_cache["price"] = price
        _price_cache["timestamp"] = now
        return price
    except Exception as e:
        logger.error(f"Error fetching BTC price: {e}")
        return _price_cache["price"]  # return stale price on error


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_strategy_data():
    """Fetch all strategy stats from the database."""
    conn = get_db()
    strategies = conn.execute("SELECT * FROM strategies").fetchall()
    btc_price = get_btc_price()

    results = []
    for s in strategies:
        sid = s["strategy_id"]

        # Cash balance
        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN side = 'BUY' THEN qty * price ELSE 0 END), 0) AS bought,
                COALESCE(SUM(CASE WHEN side = 'SELL' THEN qty * price ELSE 0 END), 0) AS sold
            FROM trades WHERE strategy_id = ?
            """,
            (sid,),
        ).fetchone()
        cash = s["initial_cash"] - row["bought"] + row["sold"]

        # Position
        pos = conn.execute(
            "SELECT qty, avg_entry_price FROM positions WHERE strategy_id = ? AND symbol = ?",
            (sid, SYMBOL),
        ).fetchone()

        qty = pos["qty"] if pos else 0
        avg_price = pos["avg_entry_price"] if pos else 0
        holdings_value = qty * btc_price
        equity = cash + holdings_value

        # P&L
        total_pnl = equity - s["initial_cash"]
        pnl_pct = (total_pnl / s["initial_cash"]) * 100 if s["initial_cash"] > 0 else 0
        unrealized = qty * (btc_price - avg_price) if qty > 0 else 0
        realized = total_pnl - unrealized

        # Trade count
        trade_count = conn.execute(
            "SELECT COUNT(*) AS cnt FROM trades WHERE strategy_id = ?", (sid,)
        ).fetchone()["cnt"]

        results.append({
            "strategy_id": sid,
            "display_name": s["display_name"],
            "state": "HOLDING" if qty > 0 else "FLAT",
            "qty": round(qty, 8),
            "cash": round(cash, 2),
            "equity": round(equity, 2),
            "pnl": round(total_pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "realized": round(realized, 2),
            "unrealized": round(unrealized, 2),
            "trade_count": trade_count,
        })

    conn.close()
    return results


def get_recent_trades(limit=50):
    """Fetch recent trades across all strategies."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_equity_series():
    """Build equity time series from trade history for charting."""
    conn = get_db()
    strategies = conn.execute("SELECT * FROM strategies").fetchall()
    btc_price = get_btc_price()

    series = {}
    for s in strategies:
        sid = s["strategy_id"]
        trades = conn.execute(
            "SELECT timestamp, side, qty, price FROM trades WHERE strategy_id = ? ORDER BY timestamp",
            (sid,),
        ).fetchall()

        # Build equity points at each trade
        cash = s["initial_cash"]
        holding_qty = 0.0
        points = [{"t": s["created_at"], "y": round(cash, 2)}]

        for t in trades:
            if t["side"] == "BUY":
                cash -= t["qty"] * t["price"]
                holding_qty += t["qty"]
            else:
                cash += t["qty"] * t["price"]
                holding_qty -= t["qty"]

            equity = cash + holding_qty * t["price"]
            points.append({"t": t["timestamp"], "y": round(equity, 2)})

        # Add current point
        current_equity = cash + holding_qty * btc_price
        points.append({"t": "now", "y": round(current_equity, 2)})

        series[sid] = points

    conn.close()
    return series


@app.route("/")
def index():
    strategies = get_strategy_data()
    trades = get_recent_trades()
    btc_price = get_btc_price()
    return render_template(
        "dashboard.html",
        strategies=strategies,
        trades=trades,
        btc_price=btc_price,
    )


@app.route("/api/strategies")
def api_strategies():
    return jsonify({
        "strategies": get_strategy_data(),
        "btc_price": get_btc_price(),
    })


@app.route("/api/equity")
def api_equity():
    return jsonify(get_equity_series())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
