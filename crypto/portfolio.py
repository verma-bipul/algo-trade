"""
Per-strategy portfolio tracker backed by Google Sheets.

Each strategy gets a virtual cash budget ($100 default) while sharing
a single Alpaca paper account. All trades go through Alpaca for real
execution, but budget enforcement and P&L tracking happen here.

Google Sheet tabs:
  - "trades"      : last 5 trades per strategy (rolling window)
  - "state"       : current cash, position per strategy (source of truth)
  - "strategies"  : strategy registry
  - "heartbeats"  : online/offline status
  - "performance" : equity & P&L for dashboard
"""

import time
from datetime import datetime, timezone

from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

from config import get_gsheet, get_logger

logger = get_logger("portfolio")

MAX_TRADES_PER_STRATEGY = 5


class PortfolioTracker:
    """Tracks a single strategy's cash, positions, and trades via Google Sheets."""

    def __init__(self, strategy_id: str, display_name: str, symbol: str = "BTC/USD", initial_cash: float = 100.0):
        self.strategy_id = strategy_id
        self.display_name = display_name
        self.symbol = symbol
        self.initial_cash = initial_cash

        # Connect to Google Sheet
        self.sheet = get_gsheet()
        self._register_strategy()

        # Load state from the "state" tab (not by replaying trades)
        self._cash = initial_cash
        self._position = {"qty": 0.0, "avg_entry_price": 0.0}
        self._held_symbol = symbol
        self._load_state()

        logger.info(
            f"[{strategy_id}] Initialized — cash=${self._cash:.2f}, "
            f"position={self._position['qty']}"
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

    def _load_state(self):
        """Load current cash and position from the state tab."""
        try:
            ws = self.sheet.worksheet("state")
            records = ws.get_all_records()
            for r in records:
                if r["strategy_id"] == self.strategy_id:
                    self._cash = float(r["cash"])
                    self._position["qty"] = float(r.get("qty", r.get("btc_qty", 0)))
                    self._position["avg_entry_price"] = float(r["avg_entry_price"])
                    self._held_symbol = str(r.get("held_symbol", self.symbol)) or self.symbol
                    return
        except Exception as e:
            logger.warning(f"Could not load state: {e}")
        # No saved state found — keep defaults (initial_cash, no position)

    def get_held_symbol(self) -> str:
        """Which symbol is currently held (matters for multi-symbol strategies)."""
        return self._held_symbol

    def _save_state(self, held_symbol: str | None = None):
        """Persist current cash and position to the state tab."""
        self._held_symbol = held_symbol or self.symbol
        row = [
            self.strategy_id,
            round(self._cash, 6),
            round(self._position["qty"], 8),
            round(self._position["avg_entry_price"], 2),
            self._held_symbol,
        ]
        try:
            ws = self.sheet.worksheet("state")
            records = ws.get_all_records()
            for i, r in enumerate(records):
                if r["strategy_id"] == self.strategy_id:
                    ws.update(f"A{i+2}:E{i+2}", [row])
                    return
            # Not found — add new row
            ws.append_row(row)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    def get_cash_balance(self) -> float:
        return self._cash

    def get_position(self, symbol: str) -> dict:
        return dict(self._position)

    def can_buy(self, symbol: str, qty: float, price: float) -> bool:
        return qty * price <= self._cash

    def _tif(self, symbol: str) -> TimeInForce:
        """GTC for crypto, DAY for stocks (fractional stock orders require DAY)."""
        return TimeInForce.GTC if "/" in symbol else TimeInForce.DAY

    def execute_buy(self, symbol: str, qty: float, trading_client) -> dict:
        """Submit a real Alpaca buy order, record at fill price."""
        logger.info(f"[{self.strategy_id}] Submitting BUY {qty:.8f} {symbol}")

        order = trading_client.submit_order(
            MarketOrderRequest(
                symbol=symbol, qty=qty, side=OrderSide.BUY, time_in_force=self._tif(symbol),
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

        # Persist to Google Sheet
        self._append_trade(symbol, "BUY", fill_qty, fill_price, str(order.id))
        self._save_state(held_symbol=symbol)
        logger.info(f"[{self.strategy_id}] BOUGHT {fill_qty:.8f} {symbol} @ ${fill_price:,.2f}")

        return {"qty": fill_qty, "price": fill_price, "order_id": str(order.id)}

    def execute_short(self, symbol: str, qty: float, trading_client) -> dict:
        """Submit a short sell (sell shares we don't own). Tracker goes negative."""
        logger.info(f"[{self.strategy_id}] Submitting SHORT {qty:.8f} {symbol}")

        order = trading_client.submit_order(
            MarketOrderRequest(
                symbol=symbol, qty=qty, side=OrderSide.SELL, time_in_force=self._tif(symbol),
            )
        )

        filled = self._wait_for_fill(order.id, trading_client)
        fill_price = float(filled.filled_avg_price)
        fill_qty = float(filled.filled_qty)

        # Track as negative position
        self._position["qty"] = -fill_qty
        self._position["avg_entry_price"] = fill_price
        self._cash += fill_qty * fill_price

        self._append_trade(symbol, "SHORT", fill_qty, fill_price, str(order.id))
        self._save_state(held_symbol=symbol)
        logger.info(f"[{self.strategy_id}] SHORTED {fill_qty:.8f} {symbol} @ ${fill_price:,.2f}")

        return {"qty": fill_qty, "price": fill_price, "order_id": str(order.id)}

    def close_short(self, symbol: str, qty: float, trading_client) -> dict:
        """Buy to cover a short position."""
        logger.info(f"[{self.strategy_id}] Submitting BUY TO COVER {qty:.8f} {symbol}")

        order = trading_client.submit_order(
            MarketOrderRequest(
                symbol=symbol, qty=qty, side=OrderSide.BUY, time_in_force=self._tif(symbol),
            )
        )

        filled = self._wait_for_fill(order.id, trading_client)
        fill_price = float(filled.filled_avg_price)
        fill_qty = float(filled.filled_qty)

        self._position["qty"] = 0
        self._position["avg_entry_price"] = 0
        self._cash -= fill_qty * fill_price

        self._append_trade(symbol, "COVER", fill_qty, fill_price, str(order.id))
        self._save_state(held_symbol=symbol)
        logger.info(f"[{self.strategy_id}] COVERED {fill_qty:.8f} {symbol} @ ${fill_price:,.2f}")

        return {"qty": fill_qty, "price": fill_price, "order_id": str(order.id)}

    def execute_sell(self, symbol: str, qty: float, trading_client) -> dict:
        """Submit a real Alpaca sell order, record at fill price."""
        logger.info(f"[{self.strategy_id}] Submitting SELL {qty:.8f} {symbol}")

        try:
            order = trading_client.submit_order(
                MarketOrderRequest(
                    symbol=symbol, qty=qty, side=OrderSide.SELL, time_in_force=self._tif(symbol),
                )
            )
        except Exception as e:
            if "insufficient balance" in str(e):
                # Retry with slightly less qty (Alpaca balance < tracker qty)
                reduced_qty = round(qty * 0.99, 8)
                logger.warning(f"[{self.strategy_id}] Retrying sell with reduced qty {reduced_qty:.8f}")
                order = trading_client.submit_order(
                    MarketOrderRequest(
                        symbol=symbol, qty=reduced_qty, side=OrderSide.SELL, time_in_force=self._tif(symbol),
                    )
                )
            else:
                raise

        filled = self._wait_for_fill(order.id, trading_client)
        fill_price = float(filled.filled_avg_price)
        fill_qty = float(filled.filled_qty)

        # Update in-memory state
        self._position["qty"] = max(self._position["qty"] - fill_qty, 0)
        if self._position["qty"] == 0:
            self._position["avg_entry_price"] = 0
        self._cash += fill_qty * fill_price

        # Persist to Google Sheet
        self._append_trade(symbol, "SELL", fill_qty, fill_price, str(order.id))
        self._save_state(held_symbol=symbol)
        logger.info(f"[{self.strategy_id}] SOLD {fill_qty:.8f} {symbol} @ ${fill_price:,.2f}")

        return {"qty": fill_qty, "price": fill_price, "order_id": str(order.id)}

    def go_to_cash(self, symbol: str, trading_client) -> dict | None:
        """Sell entire position."""
        if self._position["qty"] <= 0:
            return None
        return self.execute_sell(symbol, self._position["qty"], trading_client)

    def get_equity(self, price: float) -> float:
        return self._cash + self._position["qty"] * price

    def get_pnl(self, price: float) -> dict:
        equity = self.get_equity(price)
        total = equity - self.initial_cash
        pct = (total / self.initial_cash) * 100
        unrealized = self._position["qty"] * (
            price - self._position["avg_entry_price"]
        ) if self._position["qty"] != 0 else 0
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
                    ws.update_cell(i + 2, 2, now)
                    ws.update_cell(i + 2, 3, "running")
                    return
            ws.append_row([self.strategy_id, now, "running"])
        except Exception as e:
            logger.warning(f"Heartbeat update failed: {e}")

    def update_performance(self, price: float):
        """Write current equity/P&L to the performance sheet tab."""
        now = datetime.now(timezone.utc).isoformat()
        equity = self.get_equity(price)
        pnl = self.get_pnl(price)
        row = [
            self.strategy_id,
            now,
            round(equity, 2),
            round(self._cash, 2),
            round(self._position["qty"], 8),
            round(price, 2),
            pnl["total"],
            pnl["pct"],
        ]
        try:
            ws = self.sheet.worksheet("performance")
            records = ws.get_all_records()
            for i, r in enumerate(records):
                if r["strategy_id"] == self.strategy_id:
                    ws.update(f"A{i+2}:H{i+2}", [row])
                    return
            ws.append_row(row)
        except Exception as e:
            logger.warning(f"Performance update failed: {e}")

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
        """Append a trade and keep only the last 5 per strategy."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            ws = self.sheet.worksheet("trades")
            ws.append_row([now, self.strategy_id, symbol, side, qty, price, order_id])

            # Trim: keep only last MAX_TRADES_PER_STRATEGY for this strategy
            records = ws.get_all_records()
            my_rows = [
                (i + 2, r) for i, r in enumerate(records)
                if r["strategy_id"] == self.strategy_id
            ]
            if len(my_rows) > MAX_TRADES_PER_STRATEGY:
                rows_to_delete = [row_num for row_num, _ in my_rows[:-MAX_TRADES_PER_STRATEGY]]
                # Delete from bottom up to avoid row shift issues
                for row_num in sorted(rows_to_delete, reverse=True):
                    ws.delete_rows(row_num)
        except Exception as e:
            logger.error(f"Failed to log trade to sheet: {e}")
