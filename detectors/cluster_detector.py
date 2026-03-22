"""
Wallet Cluster Detector — detects coordinated trading by multiple wallets.
When several wallets trade the same direction on the same market within a short window,
it signals informed/coordinated activity (smart money moving together).
"""
import time
from collections import defaultdict

from stream.trade_feed import TradeFeed
from utils.logger import get_logger

log = get_logger("cluster")

# Minimum trades that must align directionally to count as a cluster
MIN_CLUSTER_SIZE = 3
# Time window to consider trades as "coordinated" (seconds)
CLUSTER_WINDOW = 30.0


class ClusterDetector:
    """Detect coordinated multi-wallet trading patterns."""

    def __init__(self, trade_feed: TradeFeed):
        self.feed = trade_feed

    def scan(self, token_id: str) -> dict:
        """
        Analyze recent trades for cluster-like coordinated activity.

        Cluster = multiple distinct trades in the same direction within a short window,
        each significantly sized, suggesting different wallets acting on the same info.

        Returns:
            {
                "score": float (-1.0 to 1.0),   # directional cluster signal
                "cluster_size": int,              # number of aligned trades
                "direction": str,                 # "buy" / "sell" / "neutral"
                "avg_size": float,                # average trade size in cluster
                "detected": bool,
            }
        """
        trades = self.feed.get_recent(token_id, n=50)
        if len(trades) < MIN_CLUSTER_SIZE:
            return self._empty_result()

        now = time.time()

        # Only consider recent trades within the cluster window
        recent = [t for t in trades if now - t.get("received_at", 0) <= CLUSTER_WINDOW]
        if len(recent) < MIN_CLUSTER_SIZE:
            return self._empty_result()

        # Count buy vs sell trades and their sizes
        buys = [t for t in recent if t.get("side", "").lower() in ("buy", "b")]
        sells = [t for t in recent if t.get("side", "").lower() in ("sell", "s")]

        buy_vol = sum(t["size"] * t["price"] for t in buys)
        sell_vol = sum(t["size"] * t["price"] for t in sells)
        total_vol = buy_vol + sell_vol

        if total_vol == 0:
            return self._empty_result()

        # Determine cluster direction
        if len(buys) >= MIN_CLUSTER_SIZE and len(buys) > len(sells) * 1.5:
            direction = "buy"
            cluster_size = len(buys)
            avg_size = buy_vol / len(buys) if buys else 0
        elif len(sells) >= MIN_CLUSTER_SIZE and len(sells) > len(buys) * 1.5:
            direction = "sell"
            cluster_size = len(sells)
            avg_size = sell_vol / len(sells) if sells else 0
        else:
            return self._empty_result()

        # Score: how concentrated + how large
        concentration = max(len(buys), len(sells)) / len(recent)
        volume_ratio = (buy_vol - sell_vol) / total_vol

        # Combine concentration (how aligned) with volume ratio (how directional)
        score = concentration * 0.6 + abs(volume_ratio) * 0.4
        if direction == "sell":
            score = -score

        detected = abs(score) > 0.15

        result = {
            "score": round(score, 4),
            "cluster_size": cluster_size,
            "direction": direction,
            "avg_size": round(avg_size, 2),
            "detected": detected,
        }

        if detected:
            emoji = "🟢" if direction == "buy" else "🔴"
            log.info(
                f"🔗 CLUSTER {emoji} {direction.upper()} | {token_id[:8]}... | "
                f"size={cluster_size} trades | "
                f"avg=${avg_size:,.0f} | "
                f"score={score:+.3f}"
            )

        return result

    def _empty_result(self) -> dict:
        return {
            "score": 0.0,
            "cluster_size": 0,
            "direction": "neutral",
            "avg_size": 0.0,
            "detected": False,
        }
