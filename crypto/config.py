"""
Shared configuration: Alpaca clients, logging, constants.
"""

import os
import logging
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.data.historical import CryptoHistoricalDataClient

load_dotenv()

API_KEY = os.getenv("APCA_API_KEY_ID")
API_SECRET = os.getenv("APCA_API_SECRET_KEY")
TRADING_ENV = os.getenv("TRADING_ENV", "paper")

if not API_KEY or not API_SECRET:
    raise RuntimeError("APCA_API_KEY_ID and APCA_API_SECRET_KEY must be set in .env")

DB_PATH = "trades.db"

# Alpaca clients (shared across strategies)
trading_client = TradingClient(API_KEY, API_SECRET, paper=(TRADING_ENV != "live"))
crypto_data_client = CryptoHistoricalDataClient(API_KEY, API_SECRET)


def get_logger(name: str) -> logging.Logger:
    """Return a logger that writes to both console and a log file."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")

    # Console handler
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # File handler
    fh = logging.FileHandler(f"{name}.log")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger
