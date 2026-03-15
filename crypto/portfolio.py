"""
Per-strategy portfolio tracker backed by Google Sheets.

Each strategy gets a virtual cash budget ($100 default) while sharing
a single Alpaca paper account. All trades go through Alpaca for real
execution, but budget enforcement and P&L tracking happen here.

Google Sheet tabs:
  - "trades"      : timestamp, strategy_id, symbol, side, qty, price, order_id
  - "strategies"  : strategy_id, display_name, initial_cash, created_at
  - "heartbeats"  : strategy_id, last_seen, status
"""

import time
from datetime import datetime, timezone

from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

from config import get_gsheet, get_logger

logger = get_logger("portfolio")


class PortfolioTracker:
    """Tracks a single strategy's cash, positions, and trades via Google Sheets."""

    def __init__(self, strategy_id: str, display_name: str, initial_cash: float = 100.0):
        self.strategy_id = strategy_id
        self.display_name = display_name
        self.initial_cash = initial_cash

        # Connect to Google Sheet
        self.sheet = get_gsheet()
        self._register_strategy()

        # Build in-memory state from existing trades
        self._cash = initial_cash
        self._position = {"qty": 0.0, "avg_entry_price": 0.0}
        self._rebuild_state()

        logger.info(
            f"[{strategy_id}] Initialized — cash=${self._cash:.2f}, "
            f"position={self._position['qty']:.8f} BTC"
        )

    def _register_strategy(self):
        """Add strategy to the strategies sheet if not already there."""
        ws = self.sheet.worksheet("strategies")
        records = ws.get_all_records()
        if not any(r["strategy_id"] == self.strategy_id for r in records):
            ws.append_row([
                self.strategy_id,
                self.display_name,
                self.initial_cash,
                datetime.now(timezone.utc).isoformat(),
            ])

    def _rebuild_state(self):
        """Read all trades from the sheet and rebuild cash + position in memory."""
        ws = self.sheet.worksheet("trades")
        records = ws.get_all_records()
        my_trades = [r for r in records if r["strategy_id"] == self.strategy_id]

        self._cash = self.initial_cash
        self._position = {"qty": 0.0, "avg_entry_price": 0.0}

        for t in my_trades:
            qty = float(t["qty"])
            price = float(t["price"])

            if t["side"] == "BUY":
                self._cash -= qty * price
                old_qty = self._position["qty"]
                old_avg = self._position["avg_entry_price"]
                new_qty = old_qty + qty
                self._position["avg_entry_price"] = (
                    ((old_qty * old_avg) + (qty * price)) / new_qty if new_qty > 0 else 0
                )
                self._position["qty"] = new_qty
            elif t["side"] == "SELL":
                self._cash += qty * price
                self._position["qty"] = max(self._position["qty"] - qty, 0)
                if self._position["qty"] == 0:
                    self._position["avg_entry_price"] = 0

    def get_cash_balance(self) -> float:
        return self._cash

    def get_position(self, symbol: str) -> dict:
        return dict(self._position)

    def can_buy(self, symbol: str, qty: float, price: float) -> bool:
        return qty * price <= self._cash

    def execute_buy(self, symbol: str, qty: float, trading_client) -> dict:
        """Submit a real Alpaca buy order, record at fill price."""
        logger.info(f"[{self.strategy_id}] Submitting BUY {qty:.8f} {symbol}")

        order = trading_client.submit_order(
            MarketOrderRequest(
                symbol=symbol, qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.GTC,
            )
        )

        filled = self._wait_for_fill(order.id, trading_client)
        fill_price = float(filled.filled_avg_price)
        fill_qty = float(filled.filled_qty)

        # Update in-memory state
        old_qty = self._position["qty"]
        old_avg = self._position["avg_entry_price"]
        new_qty = old_qty + fill_qty
        self._position["avg_entry_price"] = (
            ((old_qty * old_avg) + (fill_qty * fill_price)) / new_qty if new_qty > 0 else 0
        )
        self._position["qty"] = new_qty
        self._cash -= fill_qty * fill_price

        # Log to Google Sheet
        self._append_trade(symbol, "BUY", fill_qty, fill_price, str(order.id))
        logger.info(f"[{self.strategy_id}] BOUGHT {fill_qty:.8f} {symbol} @ ${fill_price:,.2f}")

        return {"qty": fill_qty, "price": fill_price, "order_id": str(order.id)}

    def execute_sell(self, symbol: str, qty: float, trading_client) -> dict:
        """Submit a real Alpaca sell order, record at fill price."""
        logger.info(f"[{self.strategy_id}] Submitting SELL {qty:.8f} {symbol}")

        order = trading_client.submit_order(
            MarketOrderRequest(
                symbol=symbol, qty=qty, side=OrderSide.SELL, time_in_force=TimeInForce.GTC,
            )
        )

        filled = self._wait_for_fill(order.id, trading_client)
        fill_price = float(filled.filled_avg_price)
        fill_qty = float(filled.filled_qty)

        # Update in-memory state
        self._position["qty"] = max(self._position["qty"] - fill_qty, 0)
        if self._position["qty"] == 0:
            self._position["avg_entry_price"] = 0
        self._cash += fill_qty * fill_price

        # Log to Google Sheet
        self._append_trade(symbol, "SELL", fill_qty, fill_price, str(order.id))
        logger.info(f"[{self.strategy_id}] SOLD {fill_qty:.8f} {symbol} @ ${fill_price:,.2f}")

        return {"qty": fill_qty, "price": fill_price, "order_id": str(order.id)}

    def go_to_cash(self, symbol: str, trading_client) -> dict | None:
        """Sell entire position."""
        if self._position["qty"] <= 0:
            return None
        return self.execute_sell(symbol, self._position["qty"], trading_client)

    def get_equity(self, current_prices: dict) -> float:
        return self._cash + self._position["qty"] * current_prices.get("BTC/USD", 0)

    def get_pnl(self, current_prices: dict) -> dict:
        equity = self.get_equity(current_prices)
        total = equity - self.initial_cash
        pct = (total / self.initial_cash) * 100
        unrealized = self._position["qty"] * (
            current_prices.get("BTC/USD", 0) - self._position["avg_entry_price"]
        ) if self._position["qty"] > 0 else 0
        realized = total - unrealized
        return {
            "realized": round(realized, 2),
            "unrealized": round(unrealized, 2),
            "total": round(total, 2),
            "pct": round(pct, 2),
        }

    def update_heartbeat(self):
        """Update the heartbeat timestamp so the dashboard knows we're alive."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            ws = self.sheet.worksheet("heartbeats")
            records = ws.get_all_records()
            for i, r in enumerate(records):
                if r["strategy_id"] == self.strategy_id:
                    ws.update_cell(i + 2, 2, now)  # +2: header + 0-index
                    ws.update_cell(i + 2, 3, "running")
                    return
            # Not found — add new row
            ws.append_row([self.strategy_id, now, "running"])
        except Exception as e:
            logger.warning(f"Heartbeat update failed: {e}")

    # --- Internal helpers ---

    def _wait_for_fill(self, order_id, trading_client, max_attempts: int = 30):
        """Poll until order is filled (crypto fills are usually instant)."""
        for _ in range(max_attempts):
            order = trading_client.get_order_by_id(order_id)
            if order.status.value == "filled":
                return order
            time.sleep(1)
        raise TimeoutError(f"Order {order_id} not filled after {max_attempts}s")

    def _append_trade(self, symbol: str, side: str, qty: float, price: float, order_id: str):
        """Append a trade row to the Google Sheet."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            ws = self.sheet.worksheet("trades")
            ws.append_row([now, self.strategy_id, symbol, side, qty, price, order_id])
        except Exception as e:
            logger.error(f"Failed to log trade to sheet: {e}")
