"""
Strategy 2: 1-Minute Candle Momentum on BTC/USD

Every minute:
- Fetch the last completed 1-minute candle
- Green candle (close > open) AND not holding -> BUY with full cash
- Holding -> SELL (exit after 1 candle regardless)
- Red candle AND not holding -> skip

Long-only. Position held for exactly ~1 minute.
"""

import time
from datetime import datetime, timezone, timedelta

from alpaca.data.requests import CryptoBarsRequest, CryptoLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame

from config import trading_client, crypto_data_client, get_logger
from portfolio import PortfolioTracker

SYMBOL = "BTC/USD"
BUDGET = 100.0

logger = get_logger("minute_momentum")
tracker = PortfolioTracker("minute_momentum", "1-Min Momentum BTC", initial_cash=BUDGET)


def get_btc_price() -> float:
    """Fetch current BTC/USD price."""
    quote = crypto_data_client.get_crypto_latest_quote(CryptoLatestQuoteRequest(symbol_or_symbols=SYMBOL))
    return float(quote[SYMBOL].ask_price)


def get_last_candle() -> dict | None:
    """Fetch the most recently completed 1-minute candle."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=5)

    try:
        bars = crypto_data_client.get_crypto_bars(
            CryptoBarsRequest(
                symbol_or_symbols=SYMBOL,
                timeframe=TimeFrame.Minute,
                start=start,
                end=now - timedelta(seconds=30),  # exclude current incomplete candle
            )
        )
        bar_list = bars[SYMBOL]
        if not bar_list:
            return None

        last = bar_list[-1]
        return {
            "open": float(last.open),
            "close": float(last.close),
            "high": float(last.high),
            "low": float(last.low),
            "volume": float(last.volume),
            "timestamp": last.timestamp,
        }
    except Exception as e:
        logger.error(f"Error fetching candle: {e}")
        return None


def seconds_until_next_minute() -> float:
    """Seconds until the next minute boundary + 5s buffer for candle completion."""
    now = datetime.now(timezone.utc)
    next_min = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    wait = (next_min - now).total_seconds() + 5  # 5s buffer
    return max(wait, 1)


def run():
    logger.info("=== 1-Minute Momentum Strategy Starting ===")
    logger.info(f"Budget: ${BUDGET:.2f} | Symbol: {SYMBOL}")

    while True:
        try:
            pos = tracker.get_position(SYMBOL)
            holding = pos["qty"] > 0

            # Step 1: If holding, sell (exit after 1 candle)
            if holding:
                logger.info(f"Exiting position: {pos['qty']:.8f} BTC")
                result = tracker.execute_sell(SYMBOL, pos["qty"], trading_client)
                logger.info(f"SOLD {result['qty']:.8f} @ ${result['price']:,.2f}")
                holding = False

            # Step 2: Check last candle
            candle = get_last_candle()
            if candle is None:
                logger.warning("No candle data available, skipping cycle")
            else:
                is_green = candle["close"] > candle["open"]
                color = "GREEN" if is_green else "RED"
                change_pct = ((candle["close"] - candle["open"]) / candle["open"]) * 100
                logger.info(
                    f"Candle {candle['timestamp']}: {color} "
                    f"O={candle['open']:.2f} C={candle['close']:.2f} ({change_pct:+.4f}%)"
                )

                # Step 3: If green and not holding, buy
                if is_green:
                    cash = tracker.get_cash_balance()
                    price = get_btc_price()
                    qty = round(cash / price, 8)

                    if qty > 0 and tracker.can_buy(SYMBOL, qty, price):
                        logger.info(f"GREEN signal — buying {qty:.8f} BTC")
                        result = tracker.execute_buy(SYMBOL, qty, trading_client)
                        logger.info(f"BOUGHT {result['qty']:.8f} @ ${result['price']:,.2f}")
                    else:
                        logger.warning(f"Cannot buy: cash=${cash:.2f}, price=${price:,.2f}")
                else:
                    logger.info("RED signal — skipping")

            # Log current state + heartbeat
            price = get_btc_price()
            equity = tracker.get_equity({SYMBOL: price})
            pnl = tracker.get_pnl({SYMBOL: price})
            logger.info(f"Equity=${equity:.2f} | P&L=${pnl['total']:.2f} ({pnl['pct']:.2f}%)")
            tracker.update_heartbeat()
            tracker.update_performance(price)

        except Exception as e:
            logger.error(f"Error in trading loop: {e}", exc_info=True)

        # Wait for next minute
        wait = seconds_until_next_minute()
        logger.info(f"Sleeping {wait:.0f}s until next cycle")
        time.sleep(wait)


if __name__ == "__main__":
    run()
