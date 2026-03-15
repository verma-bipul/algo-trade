"""
Per-strategy portfolio tracker backed by SQLite.

Each strategy gets a virtual cash budget ($100 default) while sharing
a single Alpaca paper account. All trades go through Alpaca for real
execution, but budget enforcement and P&L tracking happen locally.
"""

import sqlite3
import threading
from datetime import datetime, timezone

import pandas as pd
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

from config import DB_PATH, get_logger

logger = get_logger("portfolio")

_write_lock = threading.Lock()


def _init_db(conn: sqlite3.Connection):
    """Create tables if they don't exist."""
    conn.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS strategies (
            strategy_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            initial_cash REAL NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            qty REAL NOT NULL,
            price REAL NOT NULL,
            order_id TEXT,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS positions (
            strategy_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            qty REAL NOT NULL DEFAULT 0,
            avg_entry_price REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (strategy_id, symbol)
        );
    """)


class PortfolioTracker:
    """Tracks a single strategy's cash, positions, and trades."""

    def __init__(self, strategy_id: str, display_name: str, initial_cash: float = 100.0):
        self.strategy_id = strategy_id
        self.display_name = display_name
        self.initial_cash = initial_cash

        conn = self._connect()
        _init_db(conn)

        # Register strategy if new
        existing = conn.execute(
            "SELECT 1 FROM strategies WHERE strategy_id = ?", (strategy_id,)
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO strategies (strategy_id, display_name, initial_cash, created_at) VALUES (?, ?, ?, ?)",
                (strategy_id, display_name, initial_cash, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def get_cash_balance(self) -> float:
        """Cash = initial_cash - sum(buys) + sum(sells), computed from trade history."""
        conn = self._connect()
        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN side = 'BUY' THEN qty * price ELSE 0 END), 0) AS total_bought,
                COALESCE(SUM(CASE WHEN side = 'SELL' THEN qty * price ELSE 0 END), 0) AS total_sold
            FROM trades WHERE strategy_id = ?
            """,
            (self.strategy_id,),
        ).fetchone()
        conn.close()
        return self.initial_cash - row["total_bought"] + row["total_sold"]

    def get_position(self, symbol: str) -> dict:
        """Return {qty, avg_entry_price} for a symbol, or zeros if no position."""
        conn = self._connect()
        row = conn.execute(
            "SELECT qty, avg_entry_price FROM positions WHERE strategy_id = ? AND symbol = ?",
            (self.strategy_id, symbol),
        ).fetchone()
        conn.close()
        if row:
            return {"qty": row["qty"], "avg_entry_price": row["avg_entry_price"]}
        return {"qty": 0.0, "avg_entry_price": 0.0}

    def can_buy(self, symbol: str, qty: float, price: float) -> bool:
        """Check if there's enough virtual cash for this purchase."""
        return qty * price <= self.get_cash_balance()

    def execute_buy(self, symbol: str, qty: float, trading_client) -> dict:
        """Submit a real Alpaca market buy, then record at fill price."""
        logger.info(f"[{self.strategy_id}] Submitting BUY {qty:.8f} {symbol}")

        order = trading_client.submit_order(
            MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.GTC,
            )
        )

        # Wait for fill
        filled_order = self._wait_for_fill(order.id, trading_client)
        fill_price = float(filled_order.filled_avg_price)
        fill_qty = float(filled_order.filled_qty)

        self._record_trade(symbol, "BUY", fill_qty, fill_price, str(order.id))
        logger.info(f"[{self.strategy_id}] BOUGHT {fill_qty:.8f} {symbol} @ ${fill_price:,.2f}")

        return {"qty": fill_qty, "price": fill_price, "order_id": str(order.id)}

    def execute_sell(self, symbol: str, qty: float, trading_client) -> dict:
        """Submit a real Alpaca market sell, then record at fill price."""
        logger.info(f"[{self.strategy_id}] Submitting SELL {qty:.8f} {symbol}")

        order = trading_client.submit_order(
            MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.GTC,
            )
        )

        filled_order = self._wait_for_fill(order.id, trading_client)
        fill_price = float(filled_order.filled_avg_price)
        fill_qty = float(filled_order.filled_qty)

        self._record_trade(symbol, "SELL", fill_qty, fill_price, str(order.id))
        logger.info(f"[{self.strategy_id}] SOLD {fill_qty:.8f} {symbol} @ ${fill_price:,.2f}")

        return {"qty": fill_qty, "price": fill_price, "order_id": str(order.id)}

    def go_to_cash(self, symbol: str, trading_client) -> dict | None:
        """Sell entire position in a symbol. Returns None if no position."""
        pos = self.get_position(symbol)
        if pos["qty"] <= 0:
            logger.info(f"[{self.strategy_id}] No {symbol} position to sell")
            return None
        return self.execute_sell(symbol, pos["qty"], trading_client)

    def get_equity(self, current_prices: dict) -> float:
        """Total equity = cash + market value of all holdings."""
        cash = self.get_cash_balance()
        conn = self._connect()
        rows = conn.execute(
            "SELECT symbol, qty FROM positions WHERE strategy_id = ? AND qty > 0",
            (self.strategy_id,),
        ).fetchall()
        conn.close()

        holdings_value = sum(row["qty"] * current_prices.get(row["symbol"], 0) for row in rows)
        return cash + holdings_value

    def get_pnl(self, current_prices: dict) -> dict:
        """Compute realized and unrealized P&L."""
        conn = self._connect()

        # Realized P&L: sum of (sell_price - avg_entry_at_time) * qty for all sells
        # Simplified: total equity change from initial
        equity = self.get_equity(current_prices)
        total_pnl = equity - self.initial_cash
        pct = (total_pnl / self.initial_cash) * 100

        # Unrealized: current holdings value - cost basis
        rows = conn.execute(
            "SELECT symbol, qty, avg_entry_price FROM positions WHERE strategy_id = ? AND qty > 0",
            (self.strategy_id,),
        ).fetchall()
        conn.close()

        unrealized = sum(
            row["qty"] * (current_prices.get(row["symbol"], 0) - row["avg_entry_price"])
            for row in rows
        )
        realized = total_pnl - unrealized

        return {
            "realized": round(realized, 2),
            "unrealized": round(unrealized, 2),
            "total": round(total_pnl, 2),
            "pct": round(pct, 2),
        }

    def get_trade_history(self) -> pd.DataFrame:
        """Return all trades as a DataFrame."""
        conn = self._connect()
        df = pd.read_sql_query(
            "SELECT * FROM trades WHERE strategy_id = ? ORDER BY timestamp DESC",
            conn,
            params=(self.strategy_id,),
        )
        conn.close()
        return df

    # --- Internal helpers ---

    def _wait_for_fill(self, order_id, trading_client, max_attempts: int = 30):
        """Poll until order is filled (crypto fills are usually instant)."""
        import time
        for _ in range(max_attempts):
            order = trading_client.get_order_by_id(order_id)
            if order.status.value == "filled":
                return order
            time.sleep(1)
        raise TimeoutError(f"Order {order_id} not filled after {max_attempts}s")

    def _record_trade(self, symbol: str, side: str, qty: float, price: float, order_id: str):
        """Record trade and update position atomically."""
        now = datetime.now(timezone.utc).isoformat()

        with _write_lock:
            conn = self._connect()
            try:
                # Insert trade
                conn.execute(
                    "INSERT INTO trades (strategy_id, timestamp, symbol, side, qty, price, order_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (self.strategy_id, now, symbol, side, qty, price, order_id),
                )

                # Update position
                pos = conn.execute(
                    "SELECT qty, avg_entry_price FROM positions WHERE strategy_id = ? AND symbol = ?",
                    (self.strategy_id, symbol),
                ).fetchone()

                if side == "BUY":
                    if pos:
                        old_qty = pos["qty"]
                        old_avg = pos["avg_entry_price"]
                        new_qty = old_qty + qty
                        # Weighted average entry price
                        new_avg = ((old_qty * old_avg) + (qty * price)) / new_qty if new_qty > 0 else 0
                        conn.execute(
                            "UPDATE positions SET qty = ?, avg_entry_price = ? WHERE strategy_id = ? AND symbol = ?",
                            (new_qty, new_avg, self.strategy_id, symbol),
                        )
                    else:
                        conn.execute(
                            "INSERT INTO positions (strategy_id, symbol, qty, avg_entry_price) VALUES (?, ?, ?, ?)",
                            (self.strategy_id, symbol, qty, price),
                        )
                elif side == "SELL":
                    if pos:
                        new_qty = pos["qty"] - qty
                        # Keep avg_entry_price unchanged on sells (for P&L calc)
                        avg = pos["avg_entry_price"] if new_qty > 0 else 0
                        conn.execute(
                            "UPDATE positions SET qty = ?, avg_entry_price = ? WHERE strategy_id = ? AND symbol = ?",
                            (max(new_qty, 0), avg, self.strategy_id, symbol),
                        )

                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
