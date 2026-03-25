"""Centralized configuration for the arbitrage bot.

All constants are collected here. Override any value via environment variable
or an optional .env file (requires python-dotenv).
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed; use os.environ only


# --- External API URLs ---
POLYMARKET_GAMMA_URL = os.environ.get(
    "POLYMARKET_GAMMA_URL",
    "https://gamma-api.polymarket.com/events",
)
POLYMARKET_CLOB_URL = os.environ.get(
    "POLYMARKET_CLOB_URL",
    "https://clob.polymarket.com/book",
)
KALSHI_API_URL = os.environ.get(
    "KALSHI_API_URL",
    "https://api.elections.kalshi.com/trade-api/v2/markets",
)
BINANCE_PRICE_URL = os.environ.get(
    "BINANCE_PRICE_URL",
    "https://api.binance.com/api/v3/ticker/price",
)
BINANCE_KLINES_URL = os.environ.get(
    "BINANCE_KLINES_URL",
    "https://api.binance.com/api/v3/klines",
)

# --- Trading pair ---
SYMBOL = os.environ.get("SYMBOL", "BTCUSDT")

# --- Fee multipliers (parabolic: multiplier * price * (1 - price)) ---
# Polymarket crypto multiplier default is 0.0624. Update to 0.0720 via
# POLYMARKET_FEE_MULTIPLIER env var when the rate changes (target: March 30 2026).
POLYMARKET_FEE_MULTIPLIER = float(os.environ.get("POLYMARKET_FEE_MULTIPLIER", "0.0624"))
# Kalshi taker fee: ceil_to_cent(0.07 * price * (1 - price))
KALSHI_FEE_MULTIPLIER = float(os.environ.get("KALSHI_FEE_MULTIPLIER", "0.07"))

# --- HTTP settings ---
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "10"))
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))
RETRY_BASE_DELAY = float(os.environ.get("RETRY_BASE_DELAY", "1.0"))
RETRY_BACKOFF_FACTOR = float(os.environ.get("RETRY_BACKOFF_FACTOR", "2.0"))
RATE_LIMIT_BACKOFF = float(os.environ.get("RATE_LIMIT_BACKOFF", "30.0"))

# --- Polling / caching ---
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "5"))  # seconds
CACHE_TTL = float(os.environ.get("CACHE_TTL", "3.0"))  # seconds

# --- CORS ---
CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
]

# --- Logging ---
LOG_DIR = os.environ.get("LOG_DIR", "logs")
LOG_FILE = os.environ.get("LOG_FILE", "arbitrage.log")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOG_MAX_BYTES = int(os.environ.get("LOG_MAX_BYTES", str(10 * 1024 * 1024)))  # 10 MB
LOG_BACKUP_COUNT = int(os.environ.get("LOG_BACKUP_COUNT", "5"))

# --- Price sanity ---
PRICE_SUM_MIN = float(os.environ.get("PRICE_SUM_MIN", "0.85"))
PRICE_SUM_MAX = float(os.environ.get("PRICE_SUM_MAX", "1.15"))

# --- Staleness ---
DATA_STALENESS_WARN_MS = int(os.environ.get("DATA_STALENESS_WARN_MS", "5000"))
