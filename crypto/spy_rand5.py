"""
SPY Random 5-Minute Strategy

Every 5 minutes during market hours:
- Close any open position
- Flip a coin: heads -> buy, tails -> sell (short)
- Hold 5 min, close, repeat
- Market closed -> sleep 5 min, send heartbeat, check again
"""

import time
import random
from datetime import datetime, timezone, timedelta

from alpaca.data.requests import StockLatestQuoteRequest

from config import trading_client, stock_data_client, get_logger
from portfolio import PortfolioTracker

SYMBOL = "SPY"
BUDGET = 100.0
INTERVAL = 5  # minutes

logger = get_logger("spy_rand5")
tracker = PortfolioTracker("spy_rand5", "SPY Random 5-Min", symbol=SYMBOL, initial_cash=BUDGET)


def get_price() -> float:
    quote = stock_data_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=SYMBOL))
    return float(quote[SYMBOL].ask_price)


def is_market_open() -> bool:
    clock = trading_client.get_clock()
    return clock.is_open


def seconds_until_next_interval() -> float:
    now = datetime.now(timezone.utc)
    minutes_past = now.minute % INTERVAL
    next_boundary = now.replace(second=0, microsecond=0) + timedelta(minutes=INTERVAL - minutes_past)
    wait = (next_boundary - now).total_seconds() + 5
    return max(wait, 1)


def run():
    logger.info("=== SPY Random 5-Min Strategy Starting ===")

    while True:
        try:
            if not is_market_open():
                logger.info("Market closed — waiting")
                tracker.update_heartbeat()
                tracker.update_performance(get_price())
                time.sleep(300)
                continue

            # Close any open position first
            pos = tracker.get_position(SYMBOL)
            if pos["qty"] > 0:
                result = tracker.execute_sell(SYMBOL, pos["qty"], trading_client)
                logger.info(f"CLOSED {result['qty']} @ ${result['price']:,.2f}")

            # Flip a coin: heads = buy, tails = sell
            buy_signal = random.choice([True, False])
            cash = tracker.get_cash_balance()
            price = get_price()
            qty = round(cash / price, 4)

            if buy_signal:
                logger.info("HEADS — buying")
                if qty > 0 and tracker.can_buy(SYMBOL, qty, price):
                    result = tracker.execute_buy(SYMBOL, qty, trading_client)
                    logger.info(f"BOUGHT {result['qty']} @ ${result['price']:,.2f}")
            else:
                logger.info("TAILS — selling short")
                if qty > 0:
                    result = tracker.execute_sell(SYMBOL, qty, trading_client)
                    logger.info(f"SHORTED {result['qty']} @ ${result['price']:,.2f}")

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
