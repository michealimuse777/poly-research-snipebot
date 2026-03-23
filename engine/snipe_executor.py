"""
Snipe Executor — fast entry logic with early-entry conditions and cooldowns.
Only enters when momentum hasn't moved yet (catching the signal BEFORE the market).
"""
import time
from typing import Optional

import settings
from engine.position_manager import PositionManager, Position
from engine.signal_engine import SignalEngine
from stream.orderbook_cache import OrderbookCache
from utils.logger import get_logger

log = get_logger("executor")


class SnipeExecutor:
    """Execute snipe entries with strict timing and momentum filters."""

    def __init__(
        self,
        signal_engine: SignalEngine,
        position_manager: PositionManager,
        orderbook: OrderbookCache,
    ):
        self.signal = signal_engine
        self.positions = position_manager
        self.orderbook = orderbook
        self._last_trade_time: dict[str, float] = {}
        self._last_prices: dict[str, float] = {}
        self.total_signals = 0
        self.total_entries = 0
        self.total_skipped = 0

    def evaluate(self, token_id: str, market_name: str = "") -> Optional[Position]:
        """
        Evaluate a token for snipe entry.
        Returns a Position if entry was made, None otherwise.
        """
        # ── Already positioned? ─────────────────────────────
        if self.positions.has_position(token_id):
            return None

        # ── Cooldown check ──────────────────────────────────
        now = time.time()
        last_trade = self._last_trade_time.get(token_id, 0)
        if now - last_trade < settings.COOLDOWN_SECONDS:
            return None

        # ── Max positions check ─────────────────────────────
        if not self.positions.can_open():
            return None

        # ── Get current price ───────────────────────────────
        price = self._get_mid_price(token_id)
        if price <= 0:
            return None

        # ── Spread filter — block illiquid markets ──────────
        spread = self._get_spread(token_id)
        if spread > 0.15:  # >15% spread = illiquid death trap
            return None

        # ── Generate signal ─────────────────────────────────
        signal = self.signal.evaluate(token_id, market_name)
        self.total_signals += 1

        if signal["action"] == "HOLD":
            return None

        # ── Early entry check ───────────────────────────────
        # Only enter if market hasn't moved much yet (catching it early)
        last_price = self._last_prices.get(token_id, price)
        momentum = abs(price - last_price) / max(last_price, 0.001)

        if momentum > settings.MOMENTUM_ENTRY_MAX:
            log.debug(f"⏳ Skipped {token_id[:8]}... momentum={momentum:.3f} > max={settings.MOMENTUM_ENTRY_MAX}")
            self.total_skipped += 1
            self._last_prices[token_id] = price
            return None

        # ── Execute entry ───────────────────────────────────
        side = signal["action"]
        signal_strength = abs(signal.get("score", 0.0))

        # ── Score-based sizing: stronger signals = bigger bets ──
        # Base 2% of bankroll, scale up to 3% for strong signals
        size_multiplier = 1.0 + min(signal_strength, 1.0) * 0.5
        pos = self.positions.open(token_id, side, price, market_name,
                                  size_multiplier=size_multiplier)

        if pos:
            self._last_trade_time[token_id] = now
            self.total_entries += 1

            # Store signal details on position for trade logging + dynamic exits
            pos.signal_combo = signal.get("signal_combo", "unknown")
            pos.market_type = signal.get("market_type", "general")
            pos.signal_score = signal.get("score", 0.0)

            # ── Dynamic TP/SL: stronger signals get wider TP ────
            # Base: TP=5%, SL=2%. Strong signals: TP up to 7%, SL stays tight
            if signal_strength > 0.6:
                pos.dynamic_tp = 0.07
                pos.dynamic_sl = 0.02
            elif signal_strength > 0.45:
                pos.dynamic_tp = 0.06
                pos.dynamic_sl = 0.02
            else:
                pos.dynamic_tp = settings.TAKE_PROFIT
                pos.dynamic_sl = settings.STOP_LOSS

            log.info(
                f"⚡ SNIPE ENTRY {side} | {market_name or token_id[:8]} | "
                f"@ {price:.4f} | score={signal['score']:+.3f} | "
                f"type={signal.get('market_type', 'general')} | "
                f"combo={signal.get('signal_combo', '?')} | "
                f"size_mult={size_multiplier:.2f} | "
                f"TP={pos.dynamic_tp:.0%}/SL={pos.dynamic_sl:.0%} | "
                f"momentum={momentum:.4f}"
            )

        self._last_prices[token_id] = price
        return pos

    def _get_mid_price(self, token_id: str) -> float:
        """Get mid-price from orderbook."""
        book = self.orderbook.get(token_id)
        if not book:
            return 0.0

        bids = book.get("bids", [])
        asks = book.get("asks", [])

        if not bids or not asks:
            return 0.0

        best_bid = max(b["price"] for b in bids)
        best_ask = min(a["price"] for a in asks)

        return (best_bid + best_ask) / 2.0

    def _get_spread(self, token_id: str) -> float:
        """Get bid-ask spread as a percentage. High spread = illiquid."""
        book = self.orderbook.get(token_id)
        if not book:
            return 1.0  # no data = assume illiquid

        bids = book.get("bids", [])
        asks = book.get("asks", [])

        if not bids or not asks:
            return 1.0

        best_bid = max(b["price"] for b in bids)
        best_ask = min(a["price"] for a in asks)
        mid = (best_bid + best_ask) / 2.0

        if mid <= 0:
            return 1.0

        return (best_ask - best_bid) / mid
