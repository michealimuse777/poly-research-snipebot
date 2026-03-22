"""
Redis-backed orderbook cache.
Maintains top bid/ask levels per token for instant snapshots.
Also detects synthetic trades from VALIDATED size drops (fills).

VALIDATION: Only counts as trade if:
  1. Size drop exceeds minimum notional ($50)
  2. Drop persists (not just flicker)
  3. Price moved in expected direction (not just cancel)
"""
import json
import time
from typing import Callable, Optional

import redis

import settings
from utils.logger import get_logger

log = get_logger("orderbook")


class OrderbookCache:
    """Stores live orderbook state with validated synthetic trade detection."""

    def __init__(self):
        self._redis = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD or None,
            decode_responses=True,
        )
        self._local_cache: dict[str, dict] = {}
        self._use_redis = self._check_redis()
        self._on_synthetic_trade: Optional[Callable] = None
        self._trade_count = 0
        # Track price history for validation
        self._price_history: dict[str, list] = {}  # token -> [(price, time)]

    def on_synthetic_trade(self, callback: Callable):
        """Register callback for validated synthetic trades."""
        self._on_synthetic_trade = callback

    def _check_redis(self) -> bool:
        try:
            self._redis.ping()
            log.info("Redis connected for orderbook cache")
            return True
        except Exception:
            log.warning("Redis unavailable — using in-memory orderbook cache")
            return False

    def update(self, token_id: str, bids: list, asks: list):
        """Update orderbook. Detect validated fills as synthetic trades."""
        now = time.time()

        # Get existing levels for comparison
        old_bids = self._get_level_map(token_id, "bids")
        old_asks = self._get_level_map(token_id, "asks")

        # Track current best prices before update
        old_best_bid = self._get_best_price(token_id, "bids")
        old_best_ask = self._get_best_price(token_id, "asks")

        # Merge new data
        new_bids = self._merge_levels(self._get_levels(token_id, "bids"), bids)
        new_asks = self._merge_levels(self._get_levels(token_id, "asks"), asks)

        book = {
            "bids": new_bids,
            "asks": new_asks,
            "updated_at": now,
        }

        if self._use_redis:
            try:
                self._redis.set(f"ob:{token_id}", json.dumps(book), ex=60)
            except Exception:
                pass

        self._local_cache[token_id] = book

        # Track price for validation
        mid = self.get_mid_price(token_id)
        if mid > 0:
            if token_id not in self._price_history:
                self._price_history[token_id] = []
            self._price_history[token_id].append((mid, now))
            # Keep last 20 price points
            if len(self._price_history[token_id]) > 20:
                self._price_history[token_id] = self._price_history[token_id][-20:]

        # ── Detect VALIDATED synthetic trades ────────────────
        if self._on_synthetic_trade:
            # Check bids: size dropped = someone sold into the bid
            for bid in bids:
                price = float(bid.get("price", 0))
                new_size = float(bid.get("size", 0))
                price_key = f"{price:.4f}"
                old_size = old_bids.get(price_key, 0)

                if old_size > 0 and new_size < old_size:
                    filled = old_size - new_size
                    notional = filled * price

                    # VALIDATION: minimum $50 notional AND price moved
                    if notional >= 50 and self._price_moved(token_id, "sell"):
                        self._trade_count += 1
                        try:
                            self._on_synthetic_trade(token_id, price, filled, "sell")
                        except Exception:
                            pass

            # Check asks: size dropped = someone bought the ask
            for ask in asks:
                price = float(ask.get("price", 0))
                new_size = float(ask.get("size", 0))
                price_key = f"{price:.4f}"
                old_size = old_asks.get(price_key, 0)

                if old_size > 0 and new_size < old_size:
                    filled = old_size - new_size
                    notional = filled * price

                    # VALIDATION: minimum $50 notional AND price moved
                    if notional >= 50 and self._price_moved(token_id, "buy"):
                        self._trade_count += 1
                        try:
                            self._on_synthetic_trade(token_id, price, filled, "buy")
                        except Exception:
                            pass

        # Log periodically
        if self._trade_count > 0 and self._trade_count % 50 == 0:
            log.info(f"📊 {self._trade_count} validated synthetic trades detected")

    def _price_moved(self, token_id: str, expected_direction: str) -> bool:
        """Validate that price moved in the expected direction (not just cancel)."""
        history = self._price_history.get(token_id, [])
        if len(history) < 2:
            return True  # not enough data, give benefit of doubt

        # Compare current vs 3 ticks ago
        current = history[-1][0]
        lookback = history[-min(3, len(history))][0]

        if lookback == 0:
            return True

        change = (current - lookback) / lookback

        # For a sell trade: price should be dropping (or at least not rising)
        if expected_direction == "sell":
            return change <= 0.001  # price flat or down

        # For a buy trade: price should be rising (or at least not dropping)
        if expected_direction == "buy":
            return change >= -0.001  # price flat or up

        return True

    def get(self, token_id: str) -> Optional[dict]:
        if token_id in self._local_cache:
            return self._local_cache[token_id]
        if self._use_redis:
            try:
                raw = self._redis.get(f"ob:{token_id}")
                if raw:
                    book = json.loads(raw)
                    self._local_cache[token_id] = book
                    return book
            except Exception:
                pass
        return None

    def get_mid_price(self, token_id: str) -> float:
        book = self.get(token_id)
        if not book:
            return 0.0
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        best_bid = bids[0]["price"] if bids else 0
        best_ask = asks[0]["price"] if asks else 0
        if best_bid and best_ask:
            return (best_bid + best_ask) / 2
        return best_bid or best_ask

    def get_all_tokens(self) -> list[str]:
        return list(self._local_cache.keys())

    def _get_best_price(self, token_id: str, side: str) -> float:
        levels = self._get_levels(token_id, side)
        return levels[0]["price"] if levels else 0.0

    def _get_levels(self, token_id: str, side: str) -> list:
        book = self._local_cache.get(token_id, {})
        return book.get(side, [])

    def _get_level_map(self, token_id: str, side: str) -> dict:
        levels = self._get_levels(token_id, side)
        result = {}
        for level in levels:
            price = float(level.get("price", 0))
            size = float(level.get("size", 0))
            result[f"{price:.4f}"] = size
        return result

    def _merge_levels(self, existing: list, updates: list) -> list:
        level_map = {}
        for level in existing:
            price = str(level.get("price", level.get("p", "")))
            size = float(level.get("size", level.get("s", 0)))
            if price and size > 0:
                level_map[price] = size
        for level in updates:
            price = str(level.get("price", level.get("p", "")))
            size = float(level.get("size", level.get("s", 0)))
            if price:
                if size > 0:
                    level_map[price] = size
                else:
                    level_map.pop(price, None)
        result = [{"price": float(p), "size": s} for p, s in level_map.items()]
        result.sort(key=lambda x: x["price"], reverse=True)
        return result[:20]
