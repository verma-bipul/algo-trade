"""
Strategy 1: Buy & Hold BTC

Buy $100 worth of BTC at startup. Hold indefinitely.
Logs equity every 5 minutes and sends heartbeat so the dashboard knows we're alive.
This is the baseline benchmark strategy.
"""

import time
from alpaca.data.requests import CryptoLatestQuoteRequest

from config import trading_client, crypto_data_client, get_logger
from portfolio import PortfolioTracker

SYMBOL = "BTC/USD"
BUDGET = 100.0
EQUITY_LOG_INTERVAL = 300  # 5 minutes

logger = get_logger("buy_and_hold")
tracker = PortfolioTracker("buy_and_hold", "Buy & Hold BTC", initial_cash=BUDGET)


def get_btc_price() -> float:
    """Fetch current BTC/USD price from Alpaca."""
    quote = crypto_data_client.get_crypto_latest_quote(CryptoLatestQuoteRequest(symbol_or_symbols=SYMBOL))
    return float(quote[SYMBOL].ask_price)


def run():
    logger.info("=== Buy & Hold Strategy Starting ===")

    # Check if we already have a position
    pos = tracker.get_position(SYMBOL)
    if pos["qty"] > 0:
        logger.info(f"Already holding {pos['qty']:.8f} BTC @ avg ${pos['avg_entry_price']:,.2f}")
    else:
        # Buy $100 worth of BTC
        price = get_btc_price()
        qty = round(BUDGET / price, 8)

        if not tracker.can_buy(SYMBOL, qty, price):
            logger.error(f"Insufficient budget. Need ${qty * price:.2f}, have ${tracker.get_cash_balance():.2f}")
            return

        logger.info(f"Buying {qty:.8f} BTC @ ~${price:,.2f}")
        result = tracker.execute_buy(SYMBOL, qty, trading_client)
        logger.info(f"Purchase complete: {result['qty']:.8f} BTC @ ${result['price']:,.2f}")

    # Monitoring loop — log equity every 5 minutes + heartbeat
    logger.info("Entering monitoring loop (equity logged every 5 min)")
    while True:
        try:
            price = get_btc_price()
            equity = tracker.get_equity({SYMBOL: price})
            pnl = tracker.get_pnl({SYMBOL: price})
            logger.info(
                f"BTC=${price:,.2f} | Equity=${equity:.2f} | P&L=${pnl['total']:.2f} ({pnl['pct']:.2f}%)"
            )
            tracker.update_heartbeat()
        except Exception as e:
            logger.error(f"Error in monitoring loop: {e}")

        time.sleep(EQUITY_LOG_INTERVAL)


if __name__ == "__main__":
    run()
