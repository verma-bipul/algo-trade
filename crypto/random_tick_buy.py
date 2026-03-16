"""
Random Ticker Buy & Hold 30-Min Strategy

Every 30 minutes during market hours:
- Close any open position
- Pick a random stock from preprocessed universe (~6000 stocks)
- Buy it, hold 30 min, close, repeat
- Market closed -> sleep 5 min, send heartbeat, check again
"""

import time
import random
from datetime import datetime, timezone, timedelta

from alpaca.data.requests import StockLatestQuoteRequest

from config import trading_client, stock_data_client, get_logger
from portfolio import PortfolioTracker
from stock_universe import UNIVERSE

BUDGET = 100.0
INTERVAL = 30  # minutes

logger = get_logger("random_tick_buy")
tracker = PortfolioTracker("random_tick_buy", "Random Ticker 30-Min", symbol="RANDOM", initial_cash=BUDGET)

logger.info(f"Stock universe: {len(UNIVERSE)} symbols")


def get_price(symbol: str) -> float:
    quote = stock_data_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=symbol))
    return float(quote[symbol].ask_price)


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
    logger.info("=== Random Ticker 30-Min Strategy Starting ===")

    while True:
        try:
            if not is_market_open():
                logger.info("Market closed — waiting")
                tracker.update_heartbeat()
                time.sleep(300)
                continue

            # Sell whatever we're holding
            pos = tracker.get_position("RANDOM")
            held = tracker.get_held_symbol()
            if pos["qty"] > 0 and held and held != "RANDOM":
                try:
                    result = tracker.execute_sell(held, pos["qty"], trading_client)
                    logger.info(f"SOLD {held} {result['qty']} @ ${result['price']:,.2f}")
                except Exception as e:
                    logger.error(f"Failed to sell {held}: {e}")

            # Pick random stock and buy
            stock = random.choice(UNIVERSE)
            try:
                cash = tracker.get_cash_balance()
                price = get_price(stock)
                qty = round(cash / price, 4)

                if qty > 0 and tracker.can_buy(stock, qty, price):
                    result = tracker.execute_buy(stock, qty, trading_client)
                    logger.info(f"BOUGHT {stock} {result['qty']} @ ${result['price']:,.2f}")
                    tracker.update_performance(price)
                else:
                    logger.warning(f"Cannot buy {stock}: cash=${cash:.2f}, price=${price:.2f}")
            except Exception as e:
                logger.error(f"Failed to buy {stock}: {e}")

            tracker.update_heartbeat()

        except Exception as e:
            logger.error(f"Error in trading loop: {e}", exc_info=True)

        wait = seconds_until_next_interval()
        logger.info(f"Sleeping {wait:.0f}s")
        time.sleep(wait)


if __name__ == "__main__":
    run()
