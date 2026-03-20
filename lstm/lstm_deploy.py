"""
LSTM Portfolio Allocation Strategy

Runs once daily at 3:45 PM ET (or immediately if --now flag is passed).
Allocates $10,000 across 4 ETFs based on LSTM model predictions:
  VTI  (stocks), SCHZ (bonds), PDBC (commodities), VIXM (volatility)

Usage:
    python lstm_deploy.py          # continuous loop, trades at 3:45 PM ET daily
    python lstm_deploy.py --now    # trade immediately (for testing)
"""

import os
import sys
import json
import time
import logging
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
import gspread
from dotenv import load_dotenv

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestTradeRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

load_dotenv()

# --- Config ---
SYMBOLS = ["VTI", "SCHZ", "PDBC", "VIXM"]
BUDGET = 10000.0
SEQ_LEN = 50
HIDDEN_SIZE = 64
NUM_LAYERS = 1
STRATEGY_ID = "lstm_portfolio"
DISPLAY_NAME = "LSTM Portfolio $10K"

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "portfolio_net.pt")
BASE_PATH = os.path.join(os.path.dirname(__file__), "models", "base_prices.json")

API_KEY = os.getenv("APCA_API_KEY_ID")
API_SECRET = os.getenv("APCA_API_SECRET_KEY")
TRADING_ENV = os.getenv("TRADING_ENV", "paper")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")

if not API_KEY or not API_SECRET:
    raise RuntimeError("APCA_API_KEY_ID and APCA_API_SECRET_KEY must be set in .env")

trading_client = TradingClient(API_KEY, API_SECRET, paper=(TRADING_ENV != "live"))
data_client = StockHistoricalDataClient(API_KEY, API_SECRET)

# --- Logging ---
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler("logs/lstm_deploy.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("lstm_portfolio")

# --- Google Sheets ---
def get_gsheet():
    if not GOOGLE_SHEET_ID:
        return None
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        gc = gspread.service_account_from_dict(json.loads(creds_json))
    else:
        creds_file = os.getenv("GOOGLE_CREDS_FILE", "credentials.json")
        # Also check crypto folder
        if not os.path.exists(creds_file):
            alt = os.path.join(os.path.dirname(__file__), "..", "crypto", "credentials.json")
            if os.path.exists(alt):
                creds_file = alt
        gc = gspread.service_account(filename=creds_file)
    return gc.open_by_key(GOOGLE_SHEET_ID)


# --- LSTM Model ---
class PortfolioNet(nn.Module):
    def __init__(self, input_dim, hidden_size, num_assets, num_layers):
        super().__init__()
        self.lstm = nn.LSTM(input_size=input_dim, hidden_size=hidden_size,
                            num_layers=num_layers, batch_first=True)
        self.fc = nn.Linear(hidden_size, num_assets)

    def forward(self, x):
        _, (h_n, _) = self.lstm(x)
        return F.softmax(self.fc(h_n[-1]), dim=-1)


# --- Step 1: Fetch data ---
def fetch_data():
    start = datetime.now(timezone.utc) - timedelta(days=100)
    end = datetime.now(timezone.utc) - timedelta(days=1)

    bars = data_client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=SYMBOLS,
        timeframe=TimeFrame(1, TimeFrameUnit.Day),
        start=start, end=end,
    ))
    bars_df = bars.df.reset_index()
    bars_df["timestamp"] = pd.to_datetime(bars_df["timestamp"]).dt.tz_convert("America/New_York")

    closes = (bars_df.pivot(index="timestamp", columns="symbol", values="close")
              .sort_index().dropna())
    closes = closes[SYMBOLS].tail(49)

    assert len(closes) == 49, f"Expected 49 daily bars, got {len(closes)}"

    # Today's live price
    latest = data_client.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=SYMBOLS))
    today_row = pd.DataFrame(
        [[latest[sym].price for sym in SYMBOLS]],
        columns=SYMBOLS,
        index=[pd.Timestamp.now(tz="America/New_York")],
    )
    df = pd.concat([closes, today_row])

    assert len(df) == SEQ_LEN, f"Expected {SEQ_LEN} rows, got {len(df)}"
    log.info(f"Data: {len(df)} rows | Live: " +
             "  ".join(f"{s}=${latest[s].price:.2f}" for s in SYMBOLS))
    return df, {sym: latest[sym].price for sym in SYMBOLS}


# --- Step 2: Build features ---
def build_features(df):
    with open(BASE_PATH) as f:
        base_prices = json.load(f)

    prices = df[SYMBOLS].values.astype(np.float32)
    symbol_to_col = {"VTI": "stock_price", "SCHZ": "bond_price",
                     "PDBC": "commodity_price", "VIXM": "volatility_price"}
    base = np.array([base_prices[symbol_to_col[s]] for s in SYMBOLS], dtype=np.float32)

    norm_px = prices / base
    returns = np.zeros_like(prices)
    returns[1:] = np.diff(prices, axis=0) / prices[:-1]

    feat = np.concatenate([norm_px, returns], axis=1)
    X = torch.tensor(feat).unsqueeze(0)
    log.info(f"Features: {tuple(X.shape)}")
    return X


# --- Step 3: Get weights from model ---
def get_weights(X):
    model = PortfolioNet(input_dim=8, hidden_size=HIDDEN_SIZE,
                         num_assets=len(SYMBOLS), num_layers=NUM_LAYERS)
    model.load_state_dict(torch.load(MODEL_PATH, map_location="cpu", weights_only=True))
    model.eval()

    with torch.no_grad():
        weights = model(X).squeeze(0).numpy()

    for sym, w in zip(SYMBOLS, weights):
        log.info(f"  {sym}: {w*100:.1f}%")
    return weights


# --- Step 4: Execute orders ---
def execute_orders(weights, current_prices):
    """Returns list of trades executed: [{side, symbol, amount, order_id}, ...]"""
    all_positions = {p.symbol: float(p.market_value)
                     for p in trading_client.get_all_positions()}
    executed = []

    for sym, w in zip(SYMBOLS, weights):
        target_value = round(BUDGET * float(w), 2)
        current_value = all_positions.get(sym, 0.0)
        delta = target_value - current_value

        if abs(delta) < 1.0:
            log.info(f"  {sym}: ${current_value:.2f} ≈ target ${target_value:.2f} (no change)")
            continue

        side = OrderSide.BUY if delta > 0 else OrderSide.SELL
        order = trading_client.submit_order(MarketOrderRequest(
            symbol=sym,
            notional=round(abs(delta), 2),
            side=side,
            time_in_force=TimeInForce.DAY,
        ))
        log.info(f"  {side.value.upper()} {sym} ${abs(delta):.2f} "
                 f"(${current_value:.2f} → ${target_value:.2f}) order={order.id}")
        executed.append({
            "side": side.value.upper(),
            "symbol": sym,
            "amount": round(abs(delta), 2),
            "order_id": str(order.id),
        })

    return executed


# --- Step 5: Log to Google Sheets ---
def update_sheets(weights, current_prices, trades):
    try:
        sheet = get_gsheet()
        if not sheet:
            return

        now = datetime.now(timezone.utc).isoformat()

        # Calculate current portfolio value
        all_positions = {p.symbol: float(p.market_value)
                         for p in trading_client.get_all_positions()}
        portfolio_value = sum(all_positions.get(s, 0) for s in SYMBOLS)
        pnl = portfolio_value - BUDGET
        pnl_pct = (pnl / BUDGET) * 100

        # Performance tab
        perf_row = [STRATEGY_ID, now, round(portfolio_value, 2), 0,
                    0, 0, round(pnl, 2), round(pnl_pct, 2)]
        ws = sheet.worksheet("performance")
        records = ws.get_all_records()
        found = False
        for i, r in enumerate(records):
            if r["strategy_id"] == STRATEGY_ID:
                ws.update(f"A{i+2}:H{i+2}", [perf_row])
                found = True
                break
        if not found:
            ws.append_row(perf_row)

        # Heartbeat tab
        ws_hb = sheet.worksheet("heartbeats")
        hb_records = ws_hb.get_all_records()
        found = False
        for i, r in enumerate(hb_records):
            if r["strategy_id"] == STRATEGY_ID:
                ws_hb.update_cell(i + 2, 2, now)
                ws_hb.update_cell(i + 2, 3, "running")
                found = True
                break
        if not found:
            ws_hb.append_row([STRATEGY_ID, now, "running"])

        # Strategies tab (register if new)
        ws_strat = sheet.worksheet("strategies")
        strat_records = ws_strat.get_all_records()
        if not any(r["strategy_id"] == STRATEGY_ID for r in strat_records):
            ws_strat.append_row([STRATEGY_ID, DISPLAY_NAME, BUDGET, now])

        # Trades tab — log each individual trade
        ws_trades = sheet.worksheet("trades")
        for t in trades:
            ws_trades.append_row([
                now, STRATEGY_ID, t["symbol"], t["side"],
                0, t["amount"], t["order_id"],
            ])

        log.info(f"Sheets updated: equity=${portfolio_value:.2f} P&L=${pnl:.2f} ({pnl_pct:.2f}%)")
    except Exception as e:
        log.error(f"Sheets update failed: {e}")


# --- Run once ---
def run_once():
    log.info("=" * 50)
    log.info("LSTM Portfolio — running")

    df, prices = fetch_data()
    X = build_features(df)
    weights = get_weights(X)
    executed = execute_orders(weights, prices)

    # Wait a moment for orders to fill
    time.sleep(5)
    update_sheets(weights, prices, executed)

    log.info("LSTM Portfolio — done")
    log.info("=" * 50)


# --- Main loop ---
def run_loop():
    log.info("=== LSTM Portfolio Strategy Starting (daily at 3:45 PM ET) ===")

    while True:
        try:
            now_et = datetime.now(timezone.utc) - timedelta(hours=4)  # rough ET
            target = now_et.replace(hour=15, minute=45, second=0, microsecond=0)

            if now_et > target:
                # Already past 3:45 PM today, schedule for tomorrow
                target += timedelta(days=1)

            wait = (target - now_et).total_seconds()
            log.info(f"Next run at ~3:45 PM ET. Sleeping {wait/3600:.1f}h")

            # Sleep in 5-min chunks to send heartbeats
            while wait > 0:
                sleep_time = min(wait, 300)
                time.sleep(sleep_time)
                wait -= sleep_time
                try:
                    sheet = get_gsheet()
                    if sheet:
                        ws = sheet.worksheet("heartbeats")
                        records = ws.get_all_records()
                        now = datetime.now(timezone.utc).isoformat()
                        for i, r in enumerate(records):
                            if r["strategy_id"] == STRATEGY_ID:
                                ws.update_cell(i + 2, 2, now)
                                break
                except Exception:
                    pass

            # Check if market is open
            clock = trading_client.get_clock()
            if not clock.is_open:
                log.info("Market closed — skipping today")
                time.sleep(3600)
                continue

            run_once()

        except Exception as e:
            log.error(f"Error: {e}", exc_info=True)
            time.sleep(60)


if __name__ == "__main__":
    if "--now" in sys.argv:
        run_once()
    else:
        run_loop()
