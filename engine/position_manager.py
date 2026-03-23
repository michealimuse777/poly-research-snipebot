"""
Position Manager — tracks open snipe positions with entry price, time, and PnL.
"""
import time
from typing import Optional

import settings
from utils.logger import get_logger

log = get_logger("positions")


class Position:
    """A single snipe position."""

    def __init__(self, token_id: str, side: str, price: float, size: float, market_name: str = ""):
        self.token_id = token_id
        self.side = side                  # "BUY" or "SELL"
        self.entry_price = price
        self.size = size                  # dollar amount
        self.shares = size / price if price > 0 else 0
        self.market_name = market_name
        self.entry_time = time.time()
        self.exit_price: Optional[float] = None
        self.exit_time: Optional[float] = None
        self.pnl: float = 0.0
        self.exit_reason: str = ""
        self.closed = False

    def unrealized_pnl(self, current_price: float) -> float:
        """Calculate unrealized PnL at current price."""
        if self.side == "BUY":
            return (current_price - self.entry_price) * self.shares
        else:
            return (self.entry_price - current_price) * self.shares

    def unrealized_pnl_pct(self, current_price: float) -> float:
        """Calculate unrealized PnL as percentage."""
        if self.entry_price == 0:
            return 0.0
        if self.side == "BUY":
            return (current_price - self.entry_price) / self.entry_price
        else:
            return (self.entry_price - current_price) / self.entry_price

    def close(self, exit_price: float, reason: str):
        """Close the position."""
        self.exit_price = exit_price
        self.exit_time = time.time()
        self.exit_reason = reason
        self.pnl = self.unrealized_pnl(exit_price)
        self.closed = True

    def hold_time(self) -> float:
        """How long has this position been open (seconds)."""
        end = self.exit_time or time.time()
        return end - self.entry_time

    def to_dict(self) -> dict:
        return {
            "token_id": self.token_id,
            "side": self.side,
            "entry_price": self.entry_price,
            "size": self.size,
            "shares": round(self.shares, 4),
            "market_name": self.market_name,
            "entry_time": self.entry_time,
            "hold_time": round(self.hold_time(), 1),
            "pnl": round(self.pnl, 4),
            "closed": self.closed,
            "exit_reason": self.exit_reason,
        }


class PositionManager:
    """Manage all open and closed snipe positions."""

    def __init__(self):
        self.open_positions: dict[str, Position] = {}  # token_id → Position
        self.closed_positions: list[Position] = []
        self.bankroll = settings.STARTING_BANKROLL
        self.total_pnl = 0.0
        self.wins = 0
        self.losses = 0

    def can_open(self) -> bool:
        """Check if we can open a new position."""
        return len(self.open_positions) < settings.MAX_OPEN_POSITIONS

    def has_position(self, token_id: str) -> bool:
        return token_id in self.open_positions

    def open(self, token_id: str, side: str, price: float, market_name: str = "",
             size_multiplier: float = 1.0) -> Optional[Position]:
        """Open a new snipe position. size_multiplier scales the base size."""
        if not self.can_open() or self.has_position(token_id):
            return None

        size = self.bankroll * settings.POSITION_SIZE_PCT * size_multiplier
        pos = Position(token_id, side, price, size, market_name)

        self.open_positions[token_id] = pos
        self.bankroll -= size

        log.info(
            f"💰 OPEN {side} | {market_name or token_id[:8]} | "
            f"${size:.2f} @ {price:.4f} | "
            f"mult={size_multiplier:.2f} | "
            f"bankroll=${self.bankroll:.2f}"
        )

        return pos

    def close(self, token_id: str, exit_price: float, reason: str) -> Optional[Position]:
        """Close a position."""
        if token_id not in self.open_positions:
            return None

        pos = self.open_positions.pop(token_id)
        pos.close(exit_price, reason)

        self.bankroll += pos.size + pos.pnl
        self.total_pnl += pos.pnl

        if pos.pnl >= 0:
            self.wins += 1
        else:
            self.losses += 1

        pnl_pct = pos.pnl / pos.size * 100 if pos.size > 0 else 0
        emoji = "✅" if pos.pnl >= 0 else "❌"

        log.info(
            f"{emoji} CLOSE {pos.side} | {pos.market_name or token_id[:8]} | "
            f"PnL: ${pos.pnl:+.2f} ({pnl_pct:+.1f}%) | "
            f"reason={reason} | hold={pos.hold_time():.0f}s | "
            f"bankroll=${self.bankroll:.2f}"
        )

        self.closed_positions.append(pos)

        # ── Trade outcome log (CSV) ────────────────────────
        self._log_trade_outcome(pos)

        return pos

    def _log_trade_outcome(self, pos: Position):
        """Append trade outcome to trade_log.csv for edge discovery analysis."""
        import csv
        import os
        log_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "trade_log.csv")
        file_exists = os.path.exists(log_file)

        try:
            with open(log_file, "a", newline="") as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow([
                        "timestamp", "market", "market_type", "side",
                        "entry_price", "exit_price", "pnl", "pnl_pct",
                        "hold_time_s", "exit_reason", "size",
                        "signal_combo", "signal_score",
                    ])
                writer.writerow([
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                    pos.market_name or pos.token_id[:12],
                    getattr(pos, "market_type", "general"),
                    pos.side,
                    f"{pos.entry_price:.4f}",
                    f"{pos.exit_price:.4f}" if pos.exit_price else "",
                    f"{pos.pnl:.2f}",
                    f"{pos.pnl / pos.size * 100:.1f}" if pos.size > 0 else "0",
                    f"{pos.hold_time():.0f}",
                    pos.exit_reason,
                    f"{pos.size:.2f}",
                    getattr(pos, "signal_combo", "unknown"),
                    f"{getattr(pos, 'signal_score', 0.0):.4f}",
                ])
        except Exception:
            pass  # don't crash on log failure

    def get_stats(self) -> dict:
        total = self.wins + self.losses
        return {
            "open_positions": len(self.open_positions),
            "total_trades": total,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": f"{self.wins / total * 100:.1f}%" if total > 0 else "N/A",
            "total_pnl": round(self.total_pnl, 2),
            "bankroll": round(self.bankroll, 2),
        }
