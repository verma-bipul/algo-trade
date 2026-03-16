"""
Strategy 3: 5-Minute Candle Momentum on BTC/USD

Every 5 minutes:
- Green candle -> buy, hold for 5 min, sell next cycle
- Red candle -> skip
"""

import time
from datetime import datetime, timezone, timedelta

from alpaca.data.requests import CryptoBarsRequest, CryptoLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from config import trading_client, crypto_data_client, get_logger
from portfolio import PortfolioTracker

SYMBOL = "BTC/USD"
BUDGET = 100.0
INTERVAL = 5  # minutes

logger = get_logger("five_min_momentum")
tracker = PortfolioTracker("five_min_momentum", "5-Min Momentum BTC", symbol=SYMBOL, initial_cash=BUDGET)


def get_btc_price() -> float:
    quote = crypto_data_client.get_crypto_latest_quote(CryptoLatestQuoteRequest(symbol_or_symbols=SYMBOL))
    return float(quote[SYMBOL].ask_price)


def get_last_candle() -> dict | None:
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=INTERVAL * 3)
    try:
        bars = crypto_data_client.get_crypto_bars(
            CryptoBarsRequest(
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
        return {
            "open": float(last.open),
            "close": float(last.close),
            "timestamp": last.timestamp,
        }
    except Exception as e:
        logger.error(f"Error fetching candle: {e}")
        return None


def seconds_until_next_interval() -> float:
    now = datetime.now(timezone.utc)
    minutes_past = now.minute % INTERVAL
    next_boundary = now.replace(second=0, microsecond=0) + timedelta(minutes=INTERVAL - minutes_past)
    wait = (next_boundary - now).total_seconds() + 5
    return max(wait, 1)


def run():
    logger.info(f"=== {INTERVAL}-Minute Momentum Strategy Starting ===")

    while True:
        try:
            pos = tracker.get_position(SYMBOL)
            if pos["qty"] > 0:
                result = tracker.execute_sell(SYMBOL, pos["qty"], trading_client)
                logger.info(f"SOLD {result['qty']:.8f} @ ${result['price']:,.2f}")

            candle = get_last_candle()
            if candle and candle["close"] > candle["open"]:
                cash = tracker.get_cash_balance()
                price = get_btc_price()
                qty = round(cash / price, 8)
                if qty > 0 and tracker.can_buy(SYMBOL, qty, price):
                    result = tracker.execute_buy(SYMBOL, qty, trading_client)
                    logger.info(f"BOUGHT {result['qty']:.8f} @ ${result['price']:,.2f}")

            price = get_btc_price()
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
