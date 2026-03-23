"""
Exit Engine — intelligent exit logic for snipe positions.
Uses dynamic TP/SL based on signal strength.
Includes signal-flip early exit (cut losses when signal reverses).
"""
import time

import settings
from engine.position_manager import PositionManager
from engine.signal_engine import SignalEngine
from stream.orderbook_cache import OrderbookCache
from utils.logger import get_logger

log = get_logger("exit_engine")


class ExitEngine:
    """Monitor open positions and trigger smart exits."""

    def __init__(self, position_manager: PositionManager, orderbook: OrderbookCache,
                 signal_engine: SignalEngine = None):
        self.positions = position_manager
        self.orderbook = orderbook
        self.signal_engine = signal_engine
        self._signal_flip_count = 0

    def check_exits(self):
        """Check all open positions for exit conditions."""
        tokens_to_close = []

        for token_id, pos in self.positions.open_positions.items():
            price = self._get_mid_price(token_id)
            if price <= 0:
                continue

            pnl_pct = pos.unrealized_pnl_pct(price)
            hold_time = pos.hold_time()

            # ── Minimum hold time — let signal play out ────
            if hold_time < settings.MIN_HOLD_SECONDS:
                continue  # too early to exit

            # ── Dynamic TP/SL from signal strength ─────────
            tp = getattr(pos, "dynamic_tp", settings.TAKE_PROFIT)
            sl = getattr(pos, "dynamic_sl", settings.STOP_LOSS)

            # ── Take Profit ─────────────────────────────────
            if pnl_pct >= tp:
                tokens_to_close.append((token_id, price, f"TAKE_PROFIT({tp:.0%})"))
                continue

            # ── Stop Loss ───────────────────────────────────
            if pnl_pct <= -sl:
                tokens_to_close.append((token_id, price, f"STOP_LOSS({sl:.0%})"))
                continue

            # ── Signal flip early exit ──────────────────────
            # After min hold, if signal has flipped direction, cut the trade
            # Only check every ~5s (hold_time mod) to avoid over-querying
            if (self.signal_engine and hold_time >= settings.MIN_HOLD_SECONDS * 1.5
                    and int(hold_time) % 5 == 0):
                try:
                    market_name = getattr(pos, "market_name", "")
                    current_signal = self.signal_engine.evaluate(token_id, market_name)
                    current_action = current_signal.get("action", "HOLD")
                    current_score = current_signal.get("score", 0.0)

                    # Signal flipped: we're BUY but signal says SELL (or vice versa)
                    signal_flipped = (
                        (pos.side == "BUY" and current_action == "SELL") or
                        (pos.side == "SELL" and current_action == "BUY")
                    )

                    # Or signal weakened significantly toward opposite
                    signal_weakened = (
                        (pos.side == "BUY" and current_score < -0.15) or
                        (pos.side == "SELL" and current_score > 0.15)
                    )

                    if signal_flipped or signal_weakened:
                        self._signal_flip_count += 1
                        tokens_to_close.append((token_id, price, "SIGNAL_FLIP"))
                        continue
                except Exception:
                    pass  # don't crash exit loop on signal check failure

            # ── Time Exit ───────────────────────────────────
            if hold_time >= settings.TIME_EXIT_SECONDS:
                tokens_to_close.append((token_id, price, "TIME_EXIT"))
                continue

        # Execute closes outside the loop to avoid dict modification during iteration
        for token_id, price, reason in tokens_to_close:
            self.positions.close(token_id, price, reason)

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
