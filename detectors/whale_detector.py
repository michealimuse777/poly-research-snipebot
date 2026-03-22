"""
Whale Detector — detects large orders relative to market depth.
Produces a directional score: positive = bullish pressure, negative = bearish.
"""
import settings
from stream.orderbook_cache import OrderbookCache
from utils.logger import get_logger

log = get_logger("whale_detector")


class WhaleDetector:
    """Scan orderbooks for whale-sized orders and score directional pressure."""

    def __init__(self, orderbook: OrderbookCache):
        self.orderbook = orderbook
        self.threshold = settings.WHALE_THRESHOLD
        self._detections: dict[str, dict] = {}  # token_id → last detection

    def scan(self, token_id: str) -> dict:
        """
        Scan a token's orderbook for whale activity.

        Returns:
            {
                "score": float (-1.0 to 1.0),   # directional pressure
                "whale_bids": int,                # count of whale bid orders
                "whale_asks": int,                # count of whale ask orders
                "bid_volume": float,              # total whale bid volume ($)
                "ask_volume": float,              # total whale ask volume ($)
                "detected": bool,                 # any whale activity?
            }
        """
        book = self.orderbook.get(token_id)
        if not book:
            return self._empty_result()

        bids = book.get("bids", [])
        asks = book.get("asks", [])

        # Find whale-sized orders
        whale_bids = [b for b in bids if b["price"] * b["size"] >= self.threshold]
        whale_asks = [a for a in asks if a["price"] * a["size"] >= self.threshold]

        bid_volume = sum(b["price"] * b["size"] for b in whale_bids)
        ask_volume = sum(a["price"] * a["size"] for a in whale_asks)
        total = bid_volume + ask_volume

        # Directional score
        if total > 0:
            score = (bid_volume - ask_volume) / total
        else:
            score = 0.0

        detected = len(whale_bids) > 0 or len(whale_asks) > 0

        result = {
            "score": round(score, 4),
            "whale_bids": len(whale_bids),
            "whale_asks": len(whale_asks),
            "bid_volume": round(bid_volume, 2),
            "ask_volume": round(ask_volume, 2),
            "detected": detected,
        }

        if detected:
            direction = "🟢 BULLISH" if score > 0 else "🔴 BEARISH"
            log.info(
                f"🐋 WHALE {direction} | {token_id[:8]}... | "
                f"bids={len(whale_bids)} (${bid_volume:,.0f}) | "
                f"asks={len(whale_asks)} (${ask_volume:,.0f}) | "
                f"score={score:+.3f}"
            )
            self._detections[token_id] = result

        return result

    def scan_all(self) -> dict[str, dict]:
        """Scan all tokens in the orderbook cache."""
        results = {}
        for token_id in self.orderbook.get_all_tokens():
            result = self.scan(token_id)
            if result["detected"]:
                results[token_id] = result
        return results

    def _empty_result(self) -> dict:
        return {
            "score": 0.0,
            "whale_bids": 0,
            "whale_asks": 0,
            "bid_volume": 0.0,
            "ask_volume": 0.0,
            "detected": False,
        }
