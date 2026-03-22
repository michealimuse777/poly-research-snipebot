"""
Insider Detector — detects "smart money" entering before price moves.
Looks for: volume spikes, concentrated large trades, abnormal activity.
"""
import time

import settings
from stream.trade_feed import TradeFeed
from utils.logger import get_logger

log = get_logger("insider_detector")


class InsiderDetector:
    """Detect abnormal trade patterns that indicate informed trading."""

    def __init__(self, trade_feed: TradeFeed):
        self.feed = trade_feed
        self.volume_mult = settings.INSIDER_VOLUME_MULT
        self.window = settings.INSIDER_TRADE_WINDOW

    def scan(self, token_id: str) -> dict:
        """
        Analyze recent trades for insider-like activity.

        Returns:
            {
                "score": float (0.0 to 1.0),   # insider confidence
                "large_trade_ratio": float,      # % of trades that are abnormally large
                "volume_spike": float,           # current vs average volume ratio
                "buy_concentration": float,      # % of large trades that are buys
                "detected": bool,
            }
        """
        trades = self.feed.get_recent(token_id, n=self.window)

        if len(trades) < 5:
            return self._empty_result()

        # ── 1. Find abnormally large trades ─────────────────────
        sizes = [t["size"] for t in trades]
        avg_size = sum(sizes) / len(sizes)
        large_trades = [t for t in trades if t["size"] > avg_size * self.volume_mult]
        large_trade_ratio = len(large_trades) / len(trades)

        # ── 2. Volume spike (recent vs older) ───────────────────
        mid = len(trades) // 2
        recent_vol = sum(t["size"] * t["price"] for t in trades[mid:])
        older_vol = sum(t["size"] * t["price"] for t in trades[:mid])
        volume_spike = recent_vol / max(older_vol, 1.0)

        # ── 3. Buy concentration in large trades ────────────────
        if large_trades:
            buy_count = sum(1 for t in large_trades if t.get("side", "").lower() in ("buy", "b"))
            buy_concentration = buy_count / len(large_trades)
        else:
            buy_concentration = 0.5  # neutral

        # ── 4. Composite score ──────────────────────────────────
        # High large_trade_ratio + high volume_spike + directional concentration = insider
        score = (
            large_trade_ratio * 0.4 +
            min(volume_spike / 3.0, 1.0) * 0.35 +  # cap spike contribution
            abs(buy_concentration - 0.5) * 2.0 * 0.25  # how directional
        )

        # Make score directional: positive = buy pressure, negative = sell
        if buy_concentration < 0.5:
            score = -score

        detected = abs(score) > 0.15

        result = {
            "score": round(score, 4),
            "large_trade_ratio": round(large_trade_ratio, 3),
            "volume_spike": round(volume_spike, 2),
            "buy_concentration": round(buy_concentration, 3),
            "detected": detected,
        }

        if detected:
            direction = "🟢 BUY-SIDE" if score > 0 else "🔴 SELL-SIDE"
            log.info(
                f"🕵️ INSIDER {direction} | {token_id[:8]}... | "
                f"large_ratio={large_trade_ratio:.1%} | "
                f"vol_spike={volume_spike:.1f}x | "
                f"buy_conc={buy_concentration:.1%} | "
                f"score={score:+.3f}"
            )

        return result

    def _empty_result(self) -> dict:
        return {
            "score": 0.0,
            "large_trade_ratio": 0.0,
            "volume_spike": 0.0,
            "buy_concentration": 0.5,
            "detected": False,
        }
