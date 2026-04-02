# UMN Algo Trading — Team 4

Algorithmic trading system for the UMN FMA Trading Competition. Runs on a Raspberry Pi 5, trades US equities and ETFs via Alpaca paper trading.

## Strategies

| Strategy | Allocation | Asset(s) | Logic | Frequency |
|----------|-----------|----------|-------|-----------|
| **LSTM Portfolio** | 90% | VTI, SCHZ, PDBC, VIXM | Pre-trained LSTM predicts optimal allocation across stocks, bonds, commodities, and volatility | Daily at 3:45 PM ET |
| **RSI-2 Mean Reversion** | 5% | QQQ | Buy when RSI(2) < 10 (sharp drop), sell when RSI(2) > 50 (bounce). 91% historical win rate. | Daily after close |
| **Price vs 10-SMA** | 5% | SPY | Buy when price > 10-day SMA (uptrend), sell when below (trend broken) | Daily after close |

## Architecture

- **Raspberry Pi 5** (4GB) runs all 3 strategies as systemd services 24/7
- **Alpaca** paper trading API for order execution and market data
- **LSTM model** (PyTorch) — 1-layer LSTM, 64 hidden units, trained on 10 years of daily data (2016-2026), optimized for Sharpe ratio
- All strategies check after market close and place orders that fill at next open

## Setup

```bash
git clone https://github.com/verma-bipul/Algo-Trade-UMN-Team4.git
cd Algo-Trade-UMN-Team4
cp .env.example .env    # add Alpaca API keys
bash deploy/setup.sh    # installs deps, starts all 3 services
```

## Quick Test

```bash
python lstm_strategy.py --now    # immediate LSTM rebalance
python rsi2_qqq.py --now         # immediate RSI-2 check
python sma10_spy.py --now        # immediate SMA check
```

## Strategy Details

### LSTM Portfolio (90%)
Neural network trained to maximize risk-adjusted returns. Takes last 50 days of normalized prices and daily returns for 4 ETFs, outputs portfolio weights via softmax. Rebalances daily using notional (dollar-amount) orders.

### RSI-2 Mean Reversion (5%)
Connors RSI-2 strategy — exploits short-term mean reversion in QQQ. When RSI(2) drops below 10 (extremely oversold after a sharp decline), buys QQQ expecting a bounce. Sells when RSI(2) recovers above 50. Designed for volatile, uncertain markets.

### Price vs 10-day SMA (5%)
Simple momentum filter on SPY. Holds a long position when SPY is trading above its 10-day simple moving average (short-term uptrend). Exits when price drops below the average. Captures short-term trends while avoiding sustained declines.
