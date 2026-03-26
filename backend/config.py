"""Centralized configuration for the arbitrage bot.

All constants are collected here. Override any value via environment variable
or an optional .env file (requires python-dotenv).
"""
import os
from decimal import Decimal

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
POLYMARKET_FEE_MULTIPLIER = Decimal(os.environ.get("POLYMARKET_FEE_MULTIPLIER", "0.0624"))
# Kalshi taker fee: ceil_to_cent(0.07 * price * (1 - price))
KALSHI_FEE_MULTIPLIER = Decimal(os.environ.get("KALSHI_FEE_MULTIPLIER", "0.07"))

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
PRICE_SUM_MIN = Decimal(os.environ.get("PRICE_SUM_MIN", "0.85"))
PRICE_SUM_MAX = Decimal(os.environ.get("PRICE_SUM_MAX", "1.15"))

# --- Staleness ---
DATA_STALENESS_WARN_MS = int(os.environ.get("DATA_STALENESS_WARN_MS", "5000"))

# --- Execution ---
EXECUTION_ENABLED = os.environ.get("EXECUTION_ENABLED", "false").lower() == "true"
EXECUTION_DRY_RUN = os.environ.get("EXECUTION_DRY_RUN", "true").lower() == "true"
MIN_MARGIN_AFTER_FEES = Decimal(os.environ.get("MIN_MARGIN_AFTER_FEES", "0.005"))
DEFAULT_ORDER_SIZE = int(os.environ.get("DEFAULT_ORDER_SIZE", "10"))
POLY_FILL_TIMEOUT = int(os.environ.get("POLY_FILL_TIMEOUT", "30"))  # seconds
POLY_FILL_POLL_INTERVAL = float(os.environ.get("POLY_FILL_POLL_INTERVAL", "1.0"))

# --- Kalshi Auth ---
KALSHI_API_BASE_URL = os.environ.get(
    "KALSHI_API_BASE_URL",
    "https://demo-api.kalshi.co/trade-api/v2",
)
KALSHI_API_KEY_ID = os.environ.get("KALSHI_API_KEY_ID", "")
KALSHI_PRIVATE_KEY_PATH = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "")

# --- Polymarket Execution ---
POLYMARKET_HOST = os.environ.get("POLYMARKET_HOST", "https://clob.polymarket.com")
POLYMARKET_PRIVATE_KEY = os.environ.get("POLYMARKET_PRIVATE_KEY", "")
POLYMARKET_CHAIN_ID = int(os.environ.get("POLYMARKET_CHAIN_ID", "137"))
POLYMARKET_FEE_RATE_URL = os.environ.get(
    "POLYMARKET_FEE_RATE_URL",
    "https://clob.polymarket.com/fee-rate",
)

# --- WebSocket streaming ---
WS_POLYMARKET_URL = os.environ.get(
    "WS_POLYMARKET_URL",
    "wss://ws-subscriptions-clob.polymarket.com/ws/market",
)
WS_KALSHI_URL = os.environ.get(
    "WS_KALSHI_URL",
    "wss://api.elections.kalshi.com/trade-api/ws/v2",
)
WS_RECONNECT_MAX_RETRIES = int(os.environ.get("WS_RECONNECT_MAX_RETRIES", "10"))
WS_RECONNECT_BASE_DELAY = float(os.environ.get("WS_RECONNECT_BASE_DELAY", "1.0"))
WS_RECONNECT_MAX_DELAY = float(os.environ.get("WS_RECONNECT_MAX_DELAY", "60.0"))
WS_HEARTBEAT_INTERVAL = float(os.environ.get("WS_HEARTBEAT_INTERVAL", "30.0"))
WS_SCAN_INTERVAL = float(os.environ.get("WS_SCAN_INTERVAL", "0.05"))  # 50ms target
WS_FALLBACK_TO_HTTP = os.environ.get("WS_FALLBACK_TO_HTTP", "true").lower() == "true"
