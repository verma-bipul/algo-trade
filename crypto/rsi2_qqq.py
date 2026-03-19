"""
RSI-2 Mean Reversion on QQQ ($1000 budget)

Checks daily after market close (~4:05 PM ET):
- Buy when RSI(2) < 10 (sharp down day, expect bounce)
- Sell when RSI(2) > 50 (bounce happened)
- Orders fill at next market open

Runs continuously, checks once daily.
"""

import time
import math
import numpy as np
from datetime import datetime, timezone, timedelta

from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from config import trading_client, stock_data_client, get_logger
from portfolio import PortfolioTracker

SYMBOL = "QQQ"
BUDGET = 1000.0

logger = get_logger("rsi2_qqq")
tracker = PortfolioTracker("rsi2_qqq", "RSI-2 QQQ $1K", symbol=SYMBOL, initial_cash=BUDGET)


def get_price() -> float:
    quote = stock_data_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=SYMBOL))
    return float(quote[SYMBOL].ask_price)


def compute_rsi(closes: list[float], period: int = 2) -> float:
    """Compute RSI for the given period."""
    if len(closes) < period + 1:
        return 50.0  # neutral if not enough data

    deltas = np.diff(closes[-(period + 1):])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = gains.mean()
    avg_loss = losses.mean()

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def get_daily_closes(days: int = 10) -> list[float]:
    """Fetch recent daily closing prices."""
    start = datetime.now(timezone.utc) - timedelta(days=days * 2)
    end = datetime.now(timezone.utc)

    bars = stock_data_client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=SYMBOL,
        timeframe=TimeFrame(1, TimeFrameUnit.Day),
        start=start, end=end,
    ))
    bar_list = bars[SYMBOL]
    return [float(b.close) for b in bar_list]


def seconds_until_market_close() -> float:
    """Seconds until ~4:05 PM ET (5 min after close to ensure final bar is available)."""
    now_utc = datetime.now(timezone.utc)
    # ET is UTC-4 (EDT) or UTC-5 (EST). Use UTC-4 for EDT (March-November).
    now_et = now_utc - timedelta(hours=4)
    target = now_et.replace(hour=16, minute=5, second=0, microsecond=0)

    if now_et > target:
        target += timedelta(days=1)

    # Skip weekends
    while target.weekday() >= 5:
        target += timedelta(days=1)

    wait = (target - now_et).total_seconds()
    return max(wait, 1)


def run():
    logger.info("=== RSI-2 QQQ Strategy Starting ===")
    logger.info(f"Budget: ${BUDGET:.2f} | Buy: RSI(2) < 10 | Sell: RSI(2) > 50")

    while True:
        try:
            # Wait until after market close
            wait = seconds_until_market_close()
            logger.info(f"Waiting {wait/3600:.1f}h until next check (~4:05 PM ET)")

            # Sleep in 5-min chunks for heartbeats
            remaining = wait
            while remaining > 0:
                sleep_time = min(remaining, 300)
                time.sleep(sleep_time)
                remaining -= sleep_time
                tracker.update_heartbeat()

            # Check if market was open today
            clock = trading_client.get_clock()
            if not clock.is_open and clock.next_open > clock.timestamp + timedelta(hours=12):
                logger.info("Market wasn't open today — skipping")
                continue

            # Get daily closes and compute RSI(2)
            closes = get_daily_closes()
            rsi = compute_rsi(closes)
            price = closes[-1] if closes else 0
            logger.info(f"QQQ close=${price:.2f} | RSI(2)={rsi:.1f}")

            pos = tracker.get_position(SYMBOL)
            holding = pos["qty"] > 0

            if holding and rsi > 50:
                # Sell — bounce happened
                logger.info(f"RSI(2)={rsi:.1f} > 50 — SELLING (bounce complete)")
                tracker.execute_sell(SYMBOL, pos["qty"], trading_client)

            elif not holding and rsi < 10:
                # Buy — sharp drop, expect mean reversion
                cash = tracker.get_cash_balance()
                current_price = get_price()
                qty = math.floor(cash / current_price * 10000) / 10000

                if qty > 0 and tracker.can_buy(SYMBOL, qty, current_price):
                    logger.info(f"RSI(2)={rsi:.1f} < 10 — BUYING {qty} QQQ")
                    tracker.execute_buy(SYMBOL, qty, trading_client)
                else:
                    logger.warning(f"Cannot buy: cash=${cash:.2f}")

            else:
                if holding:
                    logger.info(f"RSI(2)={rsi:.1f} — holding, waiting for > 50 to sell")
                else:
                    logger.info(f"RSI(2)={rsi:.1f} — no signal, waiting for < 10 to buy")

            # Update dashboard
            current_price = get_price()
            pnl = tracker.get_pnl(current_price)
            logger.info(f"Equity=${tracker.get_equity(current_price):.2f} | P&L=${pnl['total']:.2f} ({pnl['pct']:.2f}%)")
            tracker.update_heartbeat()
            tracker.update_performance(current_price)

        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            time.sleep(60)


if __name__ == "__main__":
    run()
