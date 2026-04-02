"""
Price vs 10-day SMA on SPY — 5% of account equity

Checks daily after market close (~4:05 PM ET):
- Buy when price > 10-day SMA (short-term uptrend)
- Sell when price < 10-day SMA (uptrend broken)
- Long-only. Typical hold: 3-7 days.

SMA calculation:
    Sum of last 10 daily closes / 10

Usage:
    python sma10_spy.py          # continuous, checks daily
    python sma10_spy.py --now    # check and trade immediately
"""

import sys
import time
import math
from datetime import datetime, timezone, timedelta

from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

from config import trading_client, data_client, get_logger

SYMBOL = "SPY"
ALLOCATION = 0.05  # 5% of account
SMA_PERIOD = 10

log = get_logger("sma10_spy")


def get_daily_closes(days=20):
    """Fetch recent daily closing prices."""
    start = datetime.now(timezone.utc) - timedelta(days=days * 2)
    end = datetime.now(timezone.utc)
    bars = data_client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=SYMBOL,
        timeframe=TimeFrame(1, TimeFrameUnit.Day),
        start=start, end=end,
    ))
    return [float(b.close) for b in bars[SYMBOL]]


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
    log.info("Price vs 10-SMA SPY — checking")

    closes = get_daily_closes()
    if len(closes) < SMA_PERIOD:
        log.warning(f"Not enough data: {len(closes)} bars, need {SMA_PERIOD}")
        return

    sma = sum(closes[-SMA_PERIOD:]) / SMA_PERIOD
    price = get_price()
    current_qty = get_current_position()
    holding = current_qty > 0

    log.info(f"SPY=${price:.2f} | 10-SMA=${sma:.2f} | {'ABOVE' if price > sma else 'BELOW'}")

    if price > sma and not holding:
        equity = float(trading_client.get_account().equity)
        budget = equity * ALLOCATION
        log.info(f"Price above 10-SMA — BUYING ${budget:.2f} of SPY")
        order = trading_client.submit_order(MarketOrderRequest(
            symbol=SYMBOL, notional=round(budget, 2),
            side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
        ))
        log.info(f"Bought ~${budget:.2f} of SPY (order={order.id})")

    elif price < sma and holding:
        log.info(f"Price below 10-SMA — SELLING all SPY ({current_qty} shares)")
        trading_client.close_position(SYMBOL)
        log.info("Closed SPY position")

    else:
        if holding:
            log.info(f"Holding SPY ({current_qty} shares). Price still above 10-SMA.")
        else:
            log.info(f"No position. Price below 10-SMA, waiting for breakout.")

    log.info("=" * 50)


def run_loop():
    log.info(f"=== Price vs {SMA_PERIOD}-SMA SPY Starting ===")
    while True:
        try:
            now_et = datetime.now(timezone.utc) - timedelta(hours=4)
            target = now_et.replace(hour=16, minute=5, second=0, microsecond=0)
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
