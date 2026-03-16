"""
Random Ticker 5-Minute Strategy

Every 5 minutes:
- Close any open position
- Pick a random stock from top 1000 by volume
- Buy with available cash, hold 5 min, close, repeat
"""

import time
import math
import random
from datetime import datetime, timezone, timedelta

from alpaca.data.requests import StockLatestQuoteRequest

from config import trading_client, stock_data_client, get_logger
from portfolio import PortfolioTracker
from stock_universe import UNIVERSE

BUDGET = 100.0
INTERVAL = 5

logger = get_logger("random_tick_buy")
tracker = PortfolioTracker("random_tick_buy", "Random Ticker 5-Min", symbol="RANDOM", initial_cash=BUDGET)

logger.info(f"Stock universe: {len(UNIVERSE)} symbols")


def get_price(symbol: str) -> float:
    quote = stock_data_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=symbol))
    return float(quote[symbol].ask_price)


def seconds_until_next_interval() -> float:
    now = datetime.now(timezone.utc)
    minutes_past = now.minute % INTERVAL
    next_boundary = now.replace(second=0, microsecond=0) + timedelta(minutes=INTERVAL - minutes_past)
    wait = (next_boundary - now).total_seconds() + 5
    return max(wait, 1)


def run():
    logger.info("=== Random Ticker 5-Min Strategy Starting ===")

    while True:
        try:
            # Close whatever we're holding
            pos = tracker.get_position("RANDOM")
            held = tracker.get_held_symbol()
            if pos["qty"] > 0 and held and held != "RANDOM":
                try:
                    logger.info(f"Closing {held}: {pos['qty']} shares")
                    tracker.execute_sell(held, pos["qty"], trading_client)
                except Exception as e:
                    logger.error(f"Failed to sell {held}: {e}")

            # Pick random stock and buy
            stock = random.choice(UNIVERSE)
            try:
                cash = tracker.get_cash_balance()
                price = get_price(stock)

                if price <= 0:
                    logger.warning(f"{stock} has no price, skipping")
                else:
                    qty = math.floor(cash / price * 10000) / 10000  # round DOWN
                    if qty > 0 and tracker.can_buy(stock, qty, price):
                        logger.info(f"Buying {qty} {stock} @ ${price:.2f}")
                        result = tracker.execute_buy(stock, qty, trading_client)
                        logger.info(f"BOUGHT {stock} {result['qty']} @ ${result['price']:,.2f}")
                        tracker.update_performance(price)
                    else:
                        logger.warning(f"Cannot buy {stock}: cash=${cash:.2f}, price=${price:.2f}")
            except Exception as e:
                logger.error(f"Failed on {stock}: {e}")

            tracker.update_heartbeat()

        except Exception as e:
            logger.error(f"Error in trading loop: {e}", exc_info=True)

        wait = seconds_until_next_interval()
        logger.info(f"Sleeping {wait:.0f}s")
        time.sleep(wait)


if __name__ == "__main__":
    run()
