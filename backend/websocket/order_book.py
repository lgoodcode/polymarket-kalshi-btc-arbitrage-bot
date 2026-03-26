"""Local order book and market state management.

Maintains in-memory order book state from WebSocket snapshot/delta updates.
Used by PolymarketWebSocket and KalshiWebSocket to track current prices.
"""
import logging
import threading
from decimal import Decimal

logger = logging.getLogger(__name__)

ZERO = Decimal("0")


class OrderBook:
    """Thread-safe order book for a single asset.

    Maintains sorted price levels for bids and asks.
    Supports snapshot (full replace) and delta (incremental) updates.
    """

    def __init__(self):
        self._lock = threading.Lock()
        # price -> size mappings
        self._asks: dict[Decimal, Decimal] = {}
        self._bids: dict[Decimal, Decimal] = {}
        self._timestamp = None

    def apply_snapshot(self, asks: list[list], bids: list[list]) -> None:
        """Replace entire book with a snapshot.

        Args:
            asks: List of [price_str, size_str] pairs.
            bids: List of [price_str, size_str] pairs.
        """
        with self._lock:
            self._asks = {}
            self._bids = {}
            for price_str, size_str in asks:
                price = Decimal(str(price_str))
                size = Decimal(str(size_str))
                if size > ZERO:
                    self._asks[price] = size
            for price_str, size_str in bids:
                price = Decimal(str(price_str))
                size = Decimal(str(size_str))
                if size > ZERO:
                    self._bids[price] = size

    def apply_delta(self, asks: list[list] = None, bids: list[list] = None) -> None:
        """Apply incremental updates to the book.

        A size of 0 means remove that price level.

        Args:
            asks: List of [price_str, size_str] delta pairs.
            bids: List of [price_str, size_str] delta pairs.
        """
        with self._lock:
            if asks:
                for price_str, size_str in asks:
                    price = Decimal(str(price_str))
                    size = Decimal(str(size_str))
                    if size > ZERO:
                        self._asks[price] = size
                    else:
                        self._asks.pop(price, None)
            if bids:
                for price_str, size_str in bids:
                    price = Decimal(str(price_str))
                    size = Decimal(str(size_str))
                    if size > ZERO:
                        self._bids[price] = size
                    else:
                        self._bids.pop(price, None)

    def get_best_ask(self) -> tuple[Decimal, Decimal]:
        """Return (price, size) of the lowest ask, or (ZERO, ZERO) if empty."""
        with self._lock:
            if not self._asks:
                return ZERO, ZERO
            price = min(self._asks)
            return price, self._asks[price]

    def get_best_bid(self) -> tuple[Decimal, Decimal]:
        """Return (price, size) of the highest bid, or (ZERO, ZERO) if empty."""
        with self._lock:
            if not self._bids:
                return ZERO, ZERO
            price = max(self._bids)
            return price, self._bids[price]

    def get_depth_at_best_ask(self) -> Decimal:
        """Return total size at the best ask price level."""
        _, size = self.get_best_ask()
        return size

    def is_empty(self) -> bool:
        """Return True if the book has no levels."""
        with self._lock:
            return not self._asks and not self._bids

    def clear(self) -> None:
        """Remove all price levels."""
        with self._lock:
            self._asks.clear()
            self._bids.clear()


class MarketState:
    """Holds current state for a set of Kalshi markets.

    Thread-safe. Returns data in the same format as fetch_kalshi_data_struct()
    so run_arbitrage_checks() works unchanged.
    """

    def __init__(self):
        self._lock = threading.Lock()
        # ticker -> market dict
        self._markets: dict[str, dict] = {}

    def update_market(self, ticker: str, data: dict) -> None:
        """Update a single market's price data.

        Args:
            ticker: Market ticker string.
            data: Dict with keys: strike, yes_bid, yes_ask, no_bid, no_ask, subtitle.
                  Values should be Decimal or convertible to Decimal.
        """
        with self._lock:
            self._markets[ticker] = {
                "strike": Decimal(str(data["strike"])),
                "yes_bid": Decimal(str(data.get("yes_bid", "0"))),
                "yes_ask": Decimal(str(data.get("yes_ask", "0"))),
                "no_bid": Decimal(str(data.get("no_bid", "0"))),
                "no_ask": Decimal(str(data.get("no_ask", "0"))),
                "subtitle": data.get("subtitle", ""),
            }

    def remove_market(self, ticker: str) -> None:
        """Remove a market from state."""
        with self._lock:
            self._markets.pop(ticker, None)

    def get_markets(self) -> list[dict]:
        """Return list of market dicts sorted by strike, matching Kalshi data format."""
        with self._lock:
            markets = list(self._markets.values())
        markets.sort(key=lambda x: x["strike"])
        return markets

    def get_market(self, ticker: str) -> dict | None:
        """Return a single market's data or None."""
        with self._lock:
            return self._markets.get(ticker)

    def clear(self) -> None:
        """Remove all markets."""
        with self._lock:
            self._markets.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._markets)
