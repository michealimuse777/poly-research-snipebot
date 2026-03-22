"""
Spoofing Detector — detects fake whale orders designed to trap bots.
Large orders that appear and vanish within seconds = spoof.
Returns a penalty score to suppress false whale signals.
"""
import time
from collections import defaultdict

import settings
from utils.logger import get_logger

log = get_logger("spoofing")


class SpoofingDetector:
    """Track order persistence — flag whale orders that vanish too quickly."""

    def __init__(self):
        self.vanish_threshold = settings.SPOOF_VANISH_SECONDS
        # token_id → { price_level: { "size": size, "first_seen": time, "last_seen": time } }
        self._order_history: dict[str, dict[str, dict]] = defaultdict(dict)
        self._spoof_count: dict[str, int] = defaultdict(int)  # token → spoof counter
        self._total_spoofs = 0

    def track_order(self, token_id: str, price: float, size: float):
        """Track an order's appearance. Call on every orderbook update."""
        key = f"{price:.4f}"
        now = time.time()

        history = self._order_history[token_id]

        if size > 0:
            if key in history:
                history[key]["last_seen"] = now
                history[key]["size"] = size
            else:
                history[key] = {
                    "size": size,
                    "first_seen": now,
                    "last_seen": now,
                }
        elif key in history:
            # Order removed — check if it was a spoof
            entry = history[key]
            duration = now - entry["first_seen"]
            notional = entry["size"] * price

            if duration < self.vanish_threshold and notional > settings.WHALE_THRESHOLD * 0.5:
                self._spoof_count[token_id] += 1
                self._total_spoofs += 1
                log.warning(
                    f"⚠️ SPOOF DETECTED | {token_id[:8]}... | "
                    f"${notional:,.0f} vanished in {duration:.1f}s"
                )

            del history[key]

    def get_penalty(self, token_id: str) -> float:
        """
        Get spoof penalty for a token (0.0 to 1.0).
        Higher = more spoofing detected = less trustworthy whale signals.
        """
        count = self._spoof_count.get(token_id, 0)
        # Decay: each spoof adds 0.2 penalty, capped at 1.0
        penalty = min(count * 0.2, 1.0)
        return penalty

    def decay(self):
        """Decay spoof counts over time (call periodically)."""
        for token in list(self._spoof_count.keys()):
            self._spoof_count[token] = max(0, self._spoof_count[token] - 1)
            if self._spoof_count[token] == 0:
                del self._spoof_count[token]

    def cleanup(self):
        """Remove stale order tracking entries (older than 60s)."""
        cutoff = time.time() - 60
        for token_id in list(self._order_history.keys()):
            stale = [k for k, v in self._order_history[token_id].items() if v["last_seen"] < cutoff]
            for k in stale:
                del self._order_history[token_id][k]

    @property
    def total_spoofs(self) -> int:
        return self._total_spoofs
