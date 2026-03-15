# algo-trade

Algorithmic trading strategies using Alpaca paper trading.

## Structure

```
crypto/     # BTC/USD strategies (24/7, designed for Raspberry Pi)
stocks/     # Equity strategies (coming soon)
```

## Crypto Strategies

| Strategy | Description | Budget |
|----------|-------------|--------|
| **Buy & Hold** | Buy $100 of BTC at startup, hold forever. Benchmark. | $100 |
| **1-Min Momentum** | Green 1-min candle → buy, hold 1 min, sell. Red → skip. | $100 |

See [crypto/README.md](crypto/README.md) for setup and deployment instructions.

## Requirements

- Python 3.10+
- Alpaca paper trading account ([alpaca.markets](https://alpaca.markets))
- Raspberry Pi (or any always-on Linux box) for 24/7 crypto trading
