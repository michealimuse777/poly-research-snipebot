"""
Trade feed — ring buffer of recent trades per token.
Used by insider detector for volume spike analysis.
"""
import time
from collections import deque
from typing import Optional

from utils.logger import get_logger

log = get_logger("trade_feed")

# Max trades to keep per token
MAX_TRADES = 100


class TradeFeed:
    """Stores recent trades per token in a ring buffer."""

    def __init__(self):
        self._trades: dict[str, deque] = {}
        self._trade_count = 0

    def add_trade(self, token_id: str, price: float, size: float, side: str, timestamp: str = ""):
        """Record a new trade."""
        if token_id not in self._trades:
            self._trades[token_id] = deque(maxlen=MAX_TRADES)

        trade = {
            "price": price,
            "size": size,
            "side": side,
            "timestamp": timestamp or str(time.time()),
            "received_at": time.time(),
        }

        self._trades[token_id].append(trade)
        self._trade_count += 1

    def get_recent(self, token_id: str, n: int = 20) -> list[dict]:
        """Get the last N trades for a token."""
        if token_id not in self._trades:
            return []
        trades = list(self._trades[token_id])
        return trades[-n:]

    def get_volume(self, token_id: str, seconds: float = 60) -> float:
        """Get total volume for a token in the last N seconds."""
        if token_id not in self._trades:
            return 0.0
        cutoff = time.time() - seconds
        return sum(
            t["size"] * t["price"]
            for t in self._trades[token_id]
            if t["received_at"] >= cutoff
        )

    def get_all_tokens(self) -> list[str]:
        """Get all tokens with trade data."""
        return list(self._trades.keys())

    @property
    def total_trades(self) -> int:
        return self._trade_count
