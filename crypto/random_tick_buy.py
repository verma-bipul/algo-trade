"""
Random Ticker Buy & Hold 30-Min Strategy

Every 30 minutes during market hours:
- Pick a random stock from the top ~1000 tradeable stocks
- Buy it, hold 30 min, sell, repeat
"""

import time
import random
from datetime import datetime, timezone, timedelta

from alpaca.data.requests import StockLatestQuoteRequest
from alpaca.trading.requests import GetAssetsRequest
from alpaca.trading.enums import AssetStatus

from config import trading_client, stock_data_client, get_logger
from portfolio import PortfolioTracker

BUDGET = 100.0
INTERVAL = 30  # minutes

logger = get_logger("random_tick_buy")
tracker = PortfolioTracker("random_tick_buy", "Random Ticker 30-Min", symbol="RANDOM", initial_cash=BUDGET)

# Stock universe — built on startup, refreshed daily
_universe = []
_universe_date = None


def build_universe():
    """Get tradeable US equities from major exchanges."""
    global _universe, _universe_date
    today = datetime.now(timezone.utc).date()
    if _universe and _universe_date == today:
        return _universe

    logger.info("Building stock universe...")
    assets = trading_client.get_all_assets(GetAssetsRequest(status=AssetStatus.ACTIVE))
    _universe = [
        a.symbol for a in assets
        if a.tradable
        and a.asset_class.value == "us_equity"
        and a.exchange.value in ("NYSE", "NASDAQ", "AMEX", "ARCA")
        and a.fractionable
        and "." not in a.symbol
        and len(a.symbol) <= 5
    ]
    _universe_date = today
    logger.info(f"Universe: {len(_universe)} stocks")
    return _universe


def get_price(symbol: str) -> float:
    quote = stock_data_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=symbol))
    return float(quote[symbol].ask_price)


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
    logger.info("=== Random Ticker 30-Min Strategy Starting ===")

    while True:
        try:
            wait_for_market()
            universe = build_universe()

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
            stock = random.choice(universe)
            try:
                cash = tracker.get_cash_balance()
                price = get_price(stock)
                qty = round(cash / price, 4)

                if qty > 0 and tracker.can_buy(stock, qty, price):
                    result = tracker.execute_buy(stock, qty, trading_client)
                    logger.info(f"BOUGHT {stock} {result['qty']} @ ${result['price']:,.2f}")

                    pnl = tracker.get_pnl(price)
                    logger.info(f"Holding: {stock} | P&L=${pnl['total']:.2f} ({pnl['pct']:.2f}%)")
                    tracker.update_heartbeat()
                    tracker.update_performance(price)
                else:
                    logger.warning(f"Cannot buy {stock}: cash=${cash:.2f}, price=${price:.2f}")
            except Exception as e:
                logger.error(f"Failed to buy {stock}: {e}")
                # Still update heartbeat even if trade fails
                tracker.update_heartbeat()

        except Exception as e:
            logger.error(f"Error in trading loop: {e}", exc_info=True)

        wait = seconds_until_next_interval()
        logger.info(f"Sleeping {wait:.0f}s")
        time.sleep(wait)


if __name__ == "__main__":
    run()
