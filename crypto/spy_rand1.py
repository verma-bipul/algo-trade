"""
SPY Random 1-Minute Strategy

Every 1 minute during market hours:
- If holding, sell (close position)
- Flip a coin: heads -> buy, tails -> skip
- Hold 1 min, repeat
- Market closed -> sleep 5 min, check again
"""

import time
import random
from datetime import datetime, timezone, timedelta

from alpaca.data.requests import StockLatestQuoteRequest

from config import trading_client, stock_data_client, get_logger
from portfolio import PortfolioTracker

SYMBOL = "SPY"
BUDGET = 100.0

logger = get_logger("spy_rand1")
tracker = PortfolioTracker("spy_rand1", "SPY Random 1-Min", symbol=SYMBOL, initial_cash=BUDGET)


def get_price() -> float:
    quote = stock_data_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=SYMBOL))
    return float(quote[SYMBOL].ask_price)


def is_market_open() -> bool:
    clock = trading_client.get_clock()
    return clock.is_open


def seconds_until_next_minute() -> float:
    now = datetime.now(timezone.utc)
    next_min = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    wait = (next_min - now).total_seconds() + 5
    return max(wait, 1)


def run():
    logger.info("=== SPY Random 1-Min Strategy Starting ===")

    while True:
        try:
            if not is_market_open():
                logger.info("Market closed — waiting")
                tracker.update_heartbeat()
                time.sleep(300)
                continue

            # Close any open position
            pos = tracker.get_position(SYMBOL)
            if pos["qty"] > 0:
                result = tracker.execute_sell(SYMBOL, pos["qty"], trading_client)
                logger.info(f"SOLD {result['qty']} @ ${result['price']:,.2f}")

            # Flip a coin
            buy_signal = random.choice([True, False])

            if buy_signal:
                logger.info("HEADS — buying")
                cash = tracker.get_cash_balance()
                price = get_price()
                qty = round(cash / price, 4)
                if qty > 0 and tracker.can_buy(SYMBOL, qty, price):
                    result = tracker.execute_buy(SYMBOL, qty, trading_client)
                    logger.info(f"BOUGHT {result['qty']} @ ${result['price']:,.2f}")
            else:
                logger.info("TAILS — skip")

            price = get_price()
            pnl = tracker.get_pnl(price)
            logger.info(f"P&L=${pnl['total']:.2f} ({pnl['pct']:.2f}%)")
            tracker.update_heartbeat()
            tracker.update_performance(price)

        except Exception as e:
            logger.error(f"Error in trading loop: {e}", exc_info=True)

        wait = seconds_until_next_minute()
        logger.info(f"Sleeping {wait:.0f}s")
        time.sleep(wait)


if __name__ == "__main__":
    run()
