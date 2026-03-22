"""
Telegram Bot — alerts + status commands for the snipe bot.
Commands: /status, /positions, /pnl, /snipes, /stats
"""
import asyncio
from typing import Optional

import settings
from utils.logger import get_logger

log = get_logger("telegram")


class TelegramNotifier:
    """Send alerts and handle commands via Telegram."""

    def __init__(self, position_manager=None, snipe_executor=None):
        self.pm = position_manager
        self.executor = snipe_executor
        self._bot = None
        self._app = None
        self.enabled = bool(settings.TELEGRAM_TOKEN and settings.TELEGRAM_CHAT)

    async def start(self):
        """Start the Telegram bot."""
        if not self.enabled:
            log.warning("Telegram disabled — no token/chat ID configured")
            return

        try:
            from telegram import Bot
            from telegram.ext import Application, CommandHandler

            self._app = Application.builder().token(settings.TELEGRAM_TOKEN).build()
            self._bot = self._app.bot

            # Register commands
            self._app.add_handler(CommandHandler("status", self._cmd_status))
            self._app.add_handler(CommandHandler("positions", self._cmd_positions))
            self._app.add_handler(CommandHandler("pnl", self._cmd_pnl))
            self._app.add_handler(CommandHandler("stats", self._cmd_stats))
            self._app.add_handler(CommandHandler("snipes", self._cmd_snipes))

            await self._app.initialize()
            await self._app.start()
            await self._app.updater.start_polling(drop_pending_updates=True)

            log.info("📱 Telegram bot started")
            await self.send("🚀 *Snipe Bot Online*\nMode: PAPER\nUse /status for info")

        except ImportError:
            log.warning("python-telegram-bot not installed — Telegram disabled")
            self.enabled = False
        except Exception as e:
            log.error(f"Telegram init failed: {e}")
            self.enabled = False

    async def send(self, text: str):
        """Send a message to the configured chat."""
        if not self.enabled or not self._bot:
            return
        try:
            await self._bot.send_message(
                chat_id=settings.TELEGRAM_CHAT,
                text=text,
                parse_mode="Markdown",
            )
        except Exception as e:
            log.error(f"Telegram send failed: {e}")

    async def alert_entry(self, side: str, market: str, price: float, score: float, size: float):
        """Alert on snipe entry."""
        emoji = "🟢" if side == "BUY" else "🔴"
        await self.send(
            f"{emoji} *SNIPE ENTRY*\n"
            f"Side: {side}\n"
            f"Market: {market}\n"
            f"Price: {price:.4f}\n"
            f"Size: ${size:.2f}\n"
            f"Score: {score:+.3f}"
        )

    async def alert_exit(self, side: str, market: str, pnl: float, reason: str, hold_time: float):
        """Alert on position exit."""
        emoji = "✅" if pnl >= 0 else "❌"
        await self.send(
            f"{emoji} *SNIPE EXIT*\n"
            f"Market: {market}\n"
            f"PnL: ${pnl:+.2f}\n"
            f"Reason: {reason}\n"
            f"Hold: {hold_time:.0f}s"
        )

    # ── Command Handlers ────────────────────────────────────

    async def _cmd_status(self, update, context):
        if not self.pm:
            return
        stats = self.pm.get_stats()
        text = (
            f"📊 *Snipe Bot Status*\n"
            f"Mode: PAPER\n"
            f"Open: {stats['open_positions']}\n"
            f"Bankroll: ${stats['bankroll']:,.2f}\n"
            f"Total PnL: ${stats['total_pnl']:+.2f}\n"
            f"Win Rate: {stats['win_rate']}"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    async def _cmd_positions(self, update, context):
        if not self.pm or not self.pm.open_positions:
            await update.message.reply_text("No open positions")
            return

        lines = ["*Open Positions:*"]
        for tid, pos in self.pm.open_positions.items():
            lines.append(
                f"• {pos.market_name or tid[:8]}\n"
                f"  {pos.side} @ {pos.entry_price:.4f} | ${pos.size:.0f} | {pos.hold_time():.0f}s"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _cmd_pnl(self, update, context):
        if not self.pm:
            return
        stats = self.pm.get_stats()
        await update.message.reply_text(
            f"💰 *PnL Summary*\n"
            f"Total: ${stats['total_pnl']:+.2f}\n"
            f"Wins: {stats['wins']} | Losses: {stats['losses']}\n"
            f"Win Rate: {stats['win_rate']}\n"
            f"Bankroll: ${stats['bankroll']:,.2f}",
            parse_mode="Markdown",
        )

    async def _cmd_stats(self, update, context):
        if not self.executor:
            return
        await update.message.reply_text(
            f"📈 *Bot Stats*\n"
            f"Signals evaluated: {self.executor.total_signals}\n"
            f"Entries executed: {self.executor.total_entries}\n"
            f"Skipped (momentum): {self.executor.total_skipped}",
            parse_mode="Markdown",
        )

    async def _cmd_snipes(self, update, context):
        if not self.pm or not self.pm.closed_positions:
            await update.message.reply_text("No closed snipes yet")
            return

        lines = ["*Recent Snipes:*"]
        for pos in self.pm.closed_positions[-5:]:
            emoji = "✅" if pos.pnl >= 0 else "❌"
            lines.append(
                f"{emoji} {pos.market_name or pos.token_id[:8]}\n"
                f"  {pos.side} | PnL: ${pos.pnl:+.2f} | {pos.exit_reason} | {pos.hold_time():.0f}s"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def stop(self):
        if self._app:
            try:
                await self._app.updater.stop()
                await self._app.stop()
                await self._app.shutdown()
            except Exception:
                pass
