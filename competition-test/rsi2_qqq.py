"""
RSI-2 Mean Reversion on QQQ — 5% of account equity

Checks daily after market close (~3:50 PM ET):
- Buy when RSI(2) < 10 (sharp drop, expect bounce)
- Sell when RSI(2) > 50 (bounce happened)
- Long-only. Typical hold: 1-5 days.

RSI(2) calculation:
    1. Get last 3 daily closes → 2 daily changes
    2. avg_gain = mean of positive changes (or 0)
    3. avg_loss = mean of negative changes (or 0)
    4. RS = avg_gain / avg_loss
    5. RSI = 100 - (100 / (1 + RS))

Usage:
    python rsi2_qqq.py          # continuous, checks daily
    python rsi2_qqq.py --now    # check and trade immediately
"""

import sys
import time
import math
import numpy as np
from datetime import datetime, timezone, timedelta

from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

from config import trading_client, data_client, get_logger

SYMBOL = "QQQ"
ALLOCATION = 0.05  # 5% of account
RSI_PERIOD = 2
BUY_THRESHOLD = 10   # buy when RSI < 10
SELL_THRESHOLD = 50   # sell when RSI > 50

log = get_logger("rsi2_qqq")


def get_daily_closes(days=10):
    """Fetch recent daily closing prices."""
    start = datetime.now(timezone.utc) - timedelta(days=days * 2)
    end = datetime.now(timezone.utc)
    bars = data_client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=SYMBOL,
        timeframe=TimeFrame(1, TimeFrameUnit.Day),
        start=start, end=end,
    ))
    return [float(b.close) for b in bars[SYMBOL]]


def compute_rsi(closes, period=2):
    """
    Compute RSI for the given period.
    Needs at least (period + 1) closes.
    """
    if len(closes) < period + 1:
        return 50.0  # neutral if not enough data

    # Get last (period) daily changes
    recent = closes[-(period + 1):]
    changes = [recent[i+1] - recent[i] for i in range(len(recent)-1)]

    gains = [c for c in changes if c > 0]
    losses = [-c for c in changes if c < 0]

    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def get_price():
    quote = data_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=SYMBOL))
    return float(quote[SYMBOL].ask_price)


def get_current_position():
    for p in trading_client.get_all_positions():
        if p.symbol == SYMBOL:
            return float(p.qty)
    return 0.0


def run_once():
    log.info("=" * 50)
    log.info("RSI-2 QQQ — checking")

    closes = get_daily_closes()
    rsi = compute_rsi(closes, RSI_PERIOD)
    price = closes[-1] if closes else 0
    log.info(f"QQQ close=${price:.2f} | RSI(2)={rsi:.1f}")

    current_qty = get_current_position()
    holding = current_qty > 0

    if holding and rsi > SELL_THRESHOLD:
        log.info(f"RSI(2)={rsi:.1f} > {SELL_THRESHOLD} — SELLING (bounce complete)")
        trading_client.close_position(SYMBOL)
        log.info(f"Closed QQQ position ({current_qty} shares)")

    elif not holding and rsi < BUY_THRESHOLD:
        equity = float(trading_client.get_account().equity)
        budget = equity * ALLOCATION
        log.info(f"RSI(2)={rsi:.1f} < {BUY_THRESHOLD} — BUYING ${budget:.2f} of QQQ")
        order = trading_client.submit_order(MarketOrderRequest(
            symbol=SYMBOL, notional=round(budget, 2),
            side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
        ))
        log.info(f"Bought ~${budget:.2f} of QQQ (order={order.id})")

    else:
        if holding:
            log.info(f"Holding QQQ ({current_qty} shares). RSI(2)={rsi:.1f}, waiting for > {SELL_THRESHOLD}")
        else:
            log.info(f"No position. RSI(2)={rsi:.1f}, waiting for < {BUY_THRESHOLD}")

    log.info("=" * 50)


def run_loop():
    log.info(f"=== RSI-2 QQQ Starting (buy < {BUY_THRESHOLD}, sell > {SELL_THRESHOLD}) ===")
    while True:
        try:
            now_et = datetime.now(timezone.utc) - timedelta(hours=4)
            target = now_et.replace(hour=15, minute=50, second=0, microsecond=0)
            if now_et > target:
                target += timedelta(days=1)
            while target.weekday() >= 5:
                target += timedelta(days=1)

            wait = (target - now_et).total_seconds()
            log.info(f"Next check: {target.strftime('%A %H:%M ET')}. Sleeping {wait/3600:.1f}h")
            time.sleep(max(wait, 1))

            clock = trading_client.get_clock()
            if not clock.is_open and (clock.next_open - clock.timestamp).total_seconds() > 43200:
                log.info("Market wasn't open today — skipping")
                time.sleep(3600)
                continue

            run_once()
        except Exception as e:
            log.error(f"Error: {e}", exc_info=True)
            time.sleep(60)


if __name__ == "__main__":
    if "--now" in sys.argv:
        run_once()
    else:
        run_loop()
