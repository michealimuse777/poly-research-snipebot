"""
Exit Engine — fast exit logic for snipe positions.
TP/SL/Time-based exits. Checks every 500ms.
Snipe = fast in, fast out. No long holds.
"""
import time

import settings
from engine.position_manager import PositionManager
from stream.orderbook_cache import OrderbookCache
from utils.logger import get_logger

log = get_logger("exit_engine")


class ExitEngine:
    """Monitor open positions and trigger fast exits."""

    def __init__(self, position_manager: PositionManager, orderbook: OrderbookCache):
        self.positions = position_manager
        self.orderbook = orderbook

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

            # ── Take Profit ─────────────────────────────────
            if pnl_pct >= settings.TAKE_PROFIT:
                tokens_to_close.append((token_id, price, "TAKE_PROFIT"))
                continue

            # ── Stop Loss ───────────────────────────────────
            if pnl_pct <= -settings.STOP_LOSS:
                tokens_to_close.append((token_id, price, "STOP_LOSS"))
                continue

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
