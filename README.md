# algo-trade

Algorithmic trading strategies using Alpaca paper trading.

## Structure

```
crypto/     # BTC/USD strategies (24/7 on Raspberry Pi)
stocks/     # Equity strategies (coming soon)
```

## Crypto

Two BTC/USD strategies running on a Pi, with a Streamlit Cloud dashboard:

| Strategy | Description |
|----------|-------------|
| **Buy & Hold** | Buy $100 BTC, hold forever (benchmark) |
| **1-Min Momentum** | Green candle → buy, hold 1 min, sell |

See [crypto/README.md](crypto/README.md) for full setup instructions.

## Requirements

- Python 3.10+
- Alpaca paper trading account ([alpaca.markets](https://alpaca.markets))
- Google Cloud service account (free, for Sheets API)
- Raspberry Pi or always-on Linux box
