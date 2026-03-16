"""
SPY 30-Minute Candle Momentum

Every 30 minutes during market hours:
- Green candle -> buy, hold 30 min, sell next cycle
- Red candle -> skip
- Market closed -> sleep until open
"""

import time
from datetime import datetime, timezone, timedelta

from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from config import trading_client, stock_data_client, get_logger
from portfolio import PortfolioTracker

SYMBOL = "SPY"
BUDGET = 100.0
INTERVAL = 30  # minutes

logger = get_logger("spy_thirty_min_momentum")
tracker = PortfolioTracker("spy_thirty_min_momentum", "SPY 30-Min Momentum", symbol=SYMBOL, initial_cash=BUDGET)


def get_price() -> float:
    quote = stock_data_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=SYMBOL))
    return float(quote[SYMBOL].ask_price)


def get_last_candle() -> dict | None:
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=INTERVAL * 3)
    try:
        bars = stock_data_client.get_stock_bars(
            StockBarsRequest(
                symbol_or_symbols=SYMBOL,
                timeframe=TimeFrame(amount=INTERVAL, unit=TimeFrameUnit.Minute),
                start=start,
                end=now - timedelta(seconds=30),
            )
        )
        bar_list = bars[SYMBOL]
        if not bar_list:
            return None
        last = bar_list[-1]
        return {"open": float(last.open), "close": float(last.close)}
    except Exception as e:
        logger.error(f"Error fetching candle: {e}")
        return None


def wait_for_market():
    """If market is closed, sleep until it opens."""
    clock = trading_client.get_clock()
    if not clock.is_open:
        wait = (clock.next_open - clock.timestamp).total_seconds()
        logger.info(f"Market closed. Sleeping {wait/3600:.1f}h until {clock.next_open}")
        time.sleep(max(wait, 1))


def seconds_until_next_interval() -> float:
    now = datetime.now(timezone.utc)
    minutes_past = now.minute % INTERVAL
    next_boundary = now.replace(second=0, microsecond=0) + timedelta(minutes=INTERVAL - minutes_past)
    wait = (next_boundary - now).total_seconds() + 5
    return max(wait, 1)


def run():
    logger.info(f"=== SPY {INTERVAL}-Min Momentum Starting ===")

    while True:
        try:
            wait_for_market()

            pos = tracker.get_position(SYMBOL)
            if pos["qty"] > 0:
                result = tracker.execute_sell(SYMBOL, pos["qty"], trading_client)
                logger.info(f"SOLD {result['qty']} @ ${result['price']:,.2f}")

            candle = get_last_candle()
            if candle and candle["close"] > candle["open"]:
                cash = tracker.get_cash_balance()
                price = get_price()
                qty = round(cash / price, 4)
                if qty > 0 and tracker.can_buy(SYMBOL, qty, price):
                    result = tracker.execute_buy(SYMBOL, qty, trading_client)
                    logger.info(f"BOUGHT {result['qty']} @ ${result['price']:,.2f}")

            price = get_price()
            pnl = tracker.get_pnl(price)
            logger.info(f"P&L=${pnl['total']:.2f} ({pnl['pct']:.2f}%)")
            tracker.update_heartbeat()
            tracker.update_performance(price)

        except Exception as e:
            logger.error(f"Error in trading loop: {e}", exc_info=True)

        wait = seconds_until_next_interval()
        logger.info(f"Sleeping {wait:.0f}s")
        time.sleep(wait)


if __name__ == "__main__":
    run()
