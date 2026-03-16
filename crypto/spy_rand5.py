"""
SPY Random 5-Minute Strategy

Every 5 minutes during market hours:
- Flip a coin
- Heads -> buy SPY, hold 5 min, sell next cycle
- Tails -> skip
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


def wait_for_market():
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
    logger.info("=== SPY Random 5-Min Strategy Starting ===")

    while True:
        try:
            wait_for_market()

            # Sell if holding
            pos = tracker.get_position(SYMBOL)
            if pos["qty"] > 0:
                result = tracker.execute_sell(SYMBOL, pos["qty"], trading_client)
                logger.info(f"SOLD {result['qty']} @ ${result['price']:,.2f}")

            # Flip a coin
            buy_signal = random.choice([True, False])
            logger.info(f"Coin flip: {'HEADS (buy)' if buy_signal else 'TAILS (skip)'}")

            if buy_signal:
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
