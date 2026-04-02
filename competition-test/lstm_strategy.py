"""
LSTM Portfolio Strategy — 90% of account equity

Daily at 3:45 PM ET: LSTM predicts optimal allocation across
VTI (stocks), SCHZ (bonds), PDBC (commodities), VIXM (volatility).
Rebalances positions to match predicted weights.

Usage:
    python lstm_strategy.py          # continuous, trades daily at 3:45 PM ET
    python lstm_strategy.py --now    # trade immediately
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

from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.requests import StockBarsRequest, StockLatestTradeRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from config import trading_client, data_client, get_logger

SYMBOLS = ["VTI", "SCHZ", "PDBC", "VIXM"]
ALLOCATION = 0.90  # 90% of account
SEQ_LEN = 50
HIDDEN_SIZE = 64
NUM_LAYERS = 1

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "portfolio_net.pt")
BASE_PATH = os.path.join(os.path.dirname(__file__), "models", "base_prices.json")

log = get_logger("lstm_strategy")


class PortfolioNet(nn.Module):
    def __init__(self, input_dim, hidden_size, num_assets, num_layers):
        super().__init__()
        self.lstm = nn.LSTM(input_size=input_dim, hidden_size=hidden_size,
                            num_layers=num_layers, batch_first=True)
        self.fc = nn.Linear(hidden_size, num_assets)

    def forward(self, x):
        _, (h_n, _) = self.lstm(x)
        return F.softmax(self.fc(h_n[-1]), dim=-1)


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
    return df


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
    return torch.tensor(feat).unsqueeze(0)


def get_weights(X):
    model = PortfolioNet(8, HIDDEN_SIZE, len(SYMBOLS), NUM_LAYERS)
    model.load_state_dict(torch.load(MODEL_PATH, map_location="cpu", weights_only=True))
    model.eval()
    with torch.no_grad():
        weights = model(X).squeeze(0).numpy()
    for sym, w in zip(SYMBOLS, weights):
        log.info(f"  {sym}: {w*100:.1f}%")
    return weights


def execute_orders(weights):
    equity = float(trading_client.get_account().equity)
    budget = equity * ALLOCATION
    log.info(f"Account equity: ${equity:,.2f} | LSTM budget (90%): ${budget:,.2f}")

    all_positions = {p.symbol: float(p.market_value)
                     for p in trading_client.get_all_positions()}

    for sym, w in zip(SYMBOLS, weights):
        target_value = round(budget * float(w), 2)
        current_value = all_positions.get(sym, 0.0)
        delta = target_value - current_value

        if abs(delta) < 1.0:
            log.info(f"  {sym}: ${current_value:.2f} ≈ target ${target_value:.2f} (skip)")
            continue

        side = OrderSide.BUY if delta > 0 else OrderSide.SELL
        order = trading_client.submit_order(MarketOrderRequest(
            symbol=sym, notional=round(abs(delta), 2),
            side=side, time_in_force=TimeInForce.DAY,
        ))
        log.info(f"  {side.value.upper()} {sym} ${abs(delta):.2f} "
                 f"(${current_value:.2f} → ${target_value:.2f})")


def run_once():
    log.info("=" * 50)
    log.info("LSTM Strategy — running")
    df = fetch_data()
    X = build_features(df)
    weights = get_weights(X)
    execute_orders(weights)
    log.info("LSTM Strategy — done")
    log.info("=" * 50)


def run_loop():
    log.info("=== LSTM Strategy Starting (daily at 3:45 PM ET) ===")
    while True:
        try:
            now_et = datetime.now(timezone.utc) - timedelta(hours=4)
            target = now_et.replace(hour=15, minute=45, second=0, microsecond=0)
            if now_et > target:
                target += timedelta(days=1)
            # Skip weekends
            while target.weekday() >= 5:
                target += timedelta(days=1)

            wait = (target - now_et).total_seconds()
            log.info(f"Next run: {target.strftime('%A %H:%M ET')}. Sleeping {wait/3600:.1f}h")
            time.sleep(max(wait, 1))

            clock = trading_client.get_clock()
            if not clock.is_open:
                log.info("Market closed — skipping")
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
