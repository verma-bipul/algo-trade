"""
SPY Random 5-Minute Strategy

Every 5 minutes:
- Close any open position (long or short)
- Flip a coin: heads -> buy, tails -> short
- Hold 5 min, close, repeat
"""

import time
import random
from datetime import datetime, timezone, timedelta

from alpaca.data.requests import StockLatestQuoteRequest

from config import trading_client, stock_data_client, get_logger
from portfolio import PortfolioTracker

SYMBOL = "SPY"
BUDGET = 100.0
INTERVAL = 5

logger = get_logger("spy_rand5")
tracker = PortfolioTracker("spy_rand5", "SPY Random 5-Min", symbol=SYMBOL, initial_cash=BUDGET)


def get_price() -> float:
    quote = stock_data_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=SYMBOL))
    return float(quote[SYMBOL].ask_price)


def seconds_until_next_interval() -> float:
    now = datetime.now(timezone.utc)
    minutes_past = now.minute % INTERVAL
    next_boundary = now.replace(second=0, microsecond=0) + timedelta(minutes=INTERVAL - minutes_past)
    wait = (next_boundary - now).total_seconds() + 5
    return max(wait, 1)


def run():
    logger.info("=== SPY Random 5-Min Strategy Starting ===")
    logger.info(f"Budget: ${BUDGET:.2f} | Cash: ${tracker.get_cash_balance():.2f}")

    while True:
        try:
            pos = tracker.get_position(SYMBOL)

            # Close any open position first
            if pos["qty"] > 0:
                logger.info(f"Closing long: {pos['qty']} shares")
                tracker.execute_sell(SYMBOL, pos["qty"], trading_client)
            elif pos["qty"] < 0:
                logger.info(f"Closing short: {abs(pos['qty'])} shares")
                tracker.close_short(SYMBOL, abs(pos["qty"]), trading_client)

            # Flip a coin
            price = get_price()
            cash = tracker.get_cash_balance()
            qty = round(cash / price, 4)
            buy_signal = random.choice([True, False])

            if buy_signal:
                logger.info(f"HEADS — buying {qty} SPY @ ${price:.2f}")
                if qty > 0 and tracker.can_buy(SYMBOL, qty, price):
                    tracker.execute_buy(SYMBOL, qty, trading_client)
            else:
                logger.info(f"TAILS — shorting {qty} SPY @ ${price:.2f}")
                if qty > 0:
                    tracker.execute_short(SYMBOL, qty, trading_client)

            price = get_price()
            pnl = tracker.get_pnl(price)
            logger.info(f"Equity=${tracker.get_equity(price):.2f} | P&L=${pnl['total']:.2f} ({pnl['pct']:.2f}%)")
            tracker.update_heartbeat()
            tracker.update_performance(price)

        except Exception as e:
            logger.error(f"Error in trading loop: {e}", exc_info=True)

        wait = seconds_until_next_interval()
        logger.info(f"Sleeping {wait:.0f}s")
        time.sleep(wait)


if __name__ == "__main__":
    run()
