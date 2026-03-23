"""
Telegram Bot — full trading console for the snipe bot.

MONITORING:  /status, /positions, /trades, /signals, /whales
ANALYTICS:   /analytics (edge discovery breakdown)
CONTROL:     /pause, /resume
TUNING:      /set_confidence, /set_cooldown, /set_max_positions
AUTO-ALERTS: entries, exits (TP/SL/SIGNAL_FLIP), spoofing warnings
"""
import asyncio
import csv
import os
import time
from collections import defaultdict
from typing import Optional

import settings
from utils.logger import get_logger

log = get_logger("telegram")


class TelegramNotifier:
    """Full Telegram trading console."""

    def __init__(self, position_manager=None, snipe_executor=None,
                 signal_engine=None, whale_detector=None, spoofing_detector=None,
                 orderbook=None):
        self.pm = position_manager
        self.executor = snipe_executor
        self.signal_engine = signal_engine
        self.whale = whale_detector
        self.spoofing = spoofing_detector
        self.orderbook = orderbook
        self._bot = None
        self._app = None
        self._paused = False
        self._chat_id = settings.TELEGRAM_CHAT or None
        self.enabled = bool(settings.TELEGRAM_TOKEN)

    @property
    def is_paused(self):
        return self._paused

    async def start(self):
        """Start the Telegram bot with full command suite."""
        if not self.enabled:
            log.warning("Telegram disabled — no token configured")
            return

        try:
            from telegram import Bot, BotCommand
            from telegram.ext import Application, CommandHandler

            self._app = Application.builder().token(settings.TELEGRAM_TOKEN).build()
            self._bot = self._app.bot

            # ── Register all commands ────────────────────────
            commands = {
                # Monitoring
                "status": self._cmd_status,
                "positions": self._cmd_positions,
                "trades": self._cmd_trades,
                "signals": self._cmd_signals,
                "whales": self._cmd_whales,
                # Analytics
                "analytics": self._cmd_analytics,
                # Control
                "start": self._cmd_start,
                "pause": self._cmd_pause,
                "resume": self._cmd_resume,
                # Tuning
                "set_confidence": self._cmd_set_confidence,
                "set_cooldown": self._cmd_set_cooldown,
                "set_max_positions": self._cmd_set_max_positions,
            }

            for name, handler in commands.items():
                self._app.add_handler(CommandHandler(name, handler))

            await self._app.initialize()
            await self._app.start()
            await self._app.updater.start_polling(drop_pending_updates=True)

            # Set bot menu commands
            try:
                await self._bot.set_my_commands([
                    BotCommand("status", "📊 Bot status & PnL"),
                    BotCommand("positions", "📌 Open positions"),
                    BotCommand("trades", "📜 Recent trades"),
                    BotCommand("signals", "🧠 Live detector output"),
                    BotCommand("whales", "🐋 Whale activity"),
                    BotCommand("analytics", "📈 Edge discovery breakdown"),
                    BotCommand("pause", "⏸ Pause trading"),
                    BotCommand("resume", "▶️ Resume trading"),
                    BotCommand("set_confidence", "⚙️ Set min confidence"),
                    BotCommand("set_cooldown", "⚙️ Set cooldown seconds"),
                    BotCommand("set_max_positions", "⚙️ Set max positions"),
                ])
            except Exception:
                pass

            log.info("📱 Telegram bot started — full command suite active")
            await self.send(
                "🚀 *Snipe Bot Online*\n\n"
                "📊 /status — system state\n"
                "📌 /positions — open positions\n"
                "📜 /trades — recent trades\n"
                "🧠 /signals — live detectors\n"
                "🐋 /whales — whale activity\n"
                "📈 /analytics — edge discovery\n"
                "⏸ /pause · ▶️ /resume\n"
                "⚙️ /set\\_confidence · /set\\_cooldown · /set\\_max\\_positions"
            )

        except ImportError:
            log.warning("python-telegram-bot not installed — Telegram disabled")
            self.enabled = False
        except Exception as e:
            log.error(f"Telegram init failed: {e}")
            self.enabled = False

    # ══════════════════════════════════════════════════════════
    # MESSAGE SENDING
    # ══════════════════════════════════════════════════════════

    async def send(self, text: str, chat_id=None):
        """Send a message to the configured or auto-detected chat."""
        if not self.enabled or not self._bot:
            return
        target = chat_id or self._chat_id
        if not target:
            return
        try:
            await self._bot.send_message(
                chat_id=target,
                text=text,
                parse_mode="Markdown",
            )
        except Exception as e:
            log.error(f"Telegram send failed: {e}")

    # ══════════════════════════════════════════════════════════
    # AUTO-ALERTS (called by the engine)
    # ══════════════════════════════════════════════════════════

    async def alert_entry(self, side: str, market: str, price: float,
                          score: float, size: float, combo: str = "",
                          market_type: str = "", tp: float = 0, sl: float = 0):
        """Alert on snipe entry."""
        emoji = "🟢" if side == "BUY" else "🔴"
        await self.send(
            f"{emoji} *TRADE OPENED*\n\n"
            f"Market: {market}\n"
            f"Side: {side}\n"
            f"Price: {price:.4f}\n"
            f"Size: ${size:.2f}\n"
            f"Score: {score:+.3f}\n"
            f"Signals: {combo}\n"
            f"Type: {market_type}\n"
            f"TP: {tp:.0%} / SL: {sl:.0%}"
        )

    async def alert_exit(self, side: str, market: str, pnl: float,
                         reason: str, hold_time: float, pnl_pct: float = 0):
        """Alert on position exit."""
        if pnl >= 0:
            emoji = "💰" if "TAKE_PROFIT" in reason else "✅"
            header = "TAKE PROFIT" if "TAKE_PROFIT" in reason else "EXIT"
        else:
            emoji = "❌" if "STOP_LOSS" in reason else "⚠️"
            header = "STOP LOSS" if "STOP_LOSS" in reason else reason

        await self.send(
            f"{emoji} *{header}*\n\n"
            f"Market: {market}\n"
            f"PnL: ${pnl:+.2f} ({pnl_pct:+.1f}%)\n"
            f"Reason: {reason}\n"
            f"Hold: {hold_time:.0f}s"
        )

    async def alert_spoof(self, token_id: str, amount: float, seconds: float):
        """Alert on spoofing detection."""
        await self.send(
            f"⚠️ *SPOOF WARNING*\n\n"
            f"Token: {token_id[:12]}...\n"
            f"${amount:,.0f} vanished in {seconds:.1f}s\n"
            f"Trading blocked on this token"
        )

    # ══════════════════════════════════════════════════════════
    # MONITORING COMMANDS
    # ══════════════════════════════════════════════════════════

    async def _cmd_start(self, update, context):
        """Auto-detect chat ID on /start."""
        self._chat_id = str(update.effective_chat.id)
        log.info(f"Telegram chat ID set: {self._chat_id}")
        await update.message.reply_text(
            "✅ *Bot Connected*\n\n"
            f"Chat ID: `{self._chat_id}`\n"
            "You will now receive trade alerts.\n\n"
            "Use /status to see current state.",
            parse_mode="Markdown",
        )

    async def _cmd_status(self, update, context):
        """📊 Full system status."""
        self._auto_set_chat(update)
        if not self.pm:
            await update.message.reply_text("⚠️ Bot not fully initialized")
            return

        stats = self.pm.get_stats()
        mode = "⏸ PAUSED" if self._paused else "▶️ ACTIVE"

        # Calculate avg win/loss
        wins = [p for p in self.pm.closed_positions if p.pnl > 0]
        losses = [p for p in self.pm.closed_positions if p.pnl <= 0]
        avg_win = sum(p.pnl for p in wins) / len(wins) if wins else 0
        avg_loss = sum(p.pnl for p in losses) / len(losses) if losses else 0

        text = (
            f"📊 *BOT STATUS*\n\n"
            f"Balance: ${stats['bankroll']:,.2f}\n"
            f"PnL: ${stats['total_pnl']:+.2f}\n"
            f"Open Positions: {stats['open_positions']}/{settings.MAX_OPEN_POSITIONS}\n"
            f"Trades Closed: {stats['wins'] + stats['losses']}\n"
            f"Win Rate: {stats['win_rate']}\n"
            f"Avg Win: ${avg_win:+.2f}\n"
            f"Avg Loss: ${avg_loss:+.2f}\n\n"
            f"*System:*\n"
            f"Status: {mode}\n"
            f"Cooldown: {settings.COOLDOWN_SECONDS}s\n"
            f"Min Confidence: {settings.CONFIDENCE_MIN}\n"
            f"Min Hold: {settings.MIN_HOLD_SECONDS}s\n"
            f"TP/SL: {settings.TAKE_PROFIT:.0%}/{settings.STOP_LOSS:.0%}"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    async def _cmd_positions(self, update, context):
        """📌 Open positions with live PnL."""
        self._auto_set_chat(update)
        if not self.pm or not self.pm.open_positions:
            await update.message.reply_text("📌 No open positions")
            return

        lines = ["📌 *OPEN POSITIONS*\n"]
        for i, (tid, pos) in enumerate(self.pm.open_positions.items(), 1):
            # Get current price
            current = 0.0
            if self.orderbook:
                book = self.orderbook.get(tid)
                if book:
                    bids = book.get("bids", [])
                    asks = book.get("asks", [])
                    if bids and asks:
                        current = (max(b["price"] for b in bids) +
                                   min(a["price"] for a in asks)) / 2.0

            pnl = pos.unrealized_pnl(current) if current > 0 else 0
            combo = getattr(pos, "signal_combo", "?")
            tp = getattr(pos, "dynamic_tp", settings.TAKE_PROFIT)
            sl = getattr(pos, "dynamic_sl", settings.STOP_LOSS)

            emoji = "🟢" if pnl >= 0 else "🔴"
            lines.append(
                f"{i}. *{pos.market_name or tid[:12]}*\n"
                f"   Side: {pos.side}\n"
                f"   Entry: {pos.entry_price:.4f}"
                f"{f' → {current:.4f}' if current > 0 else ''}\n"
                f"   {emoji} PnL: ${pnl:+.2f}\n"
                f"   Signals: {combo}\n"
                f"   Hold: {pos.hold_time():.0f}s | TP: {tp:.0%} SL: {sl:.0%}\n"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _cmd_trades(self, update, context):
        """📜 Recent closed trades."""
        self._auto_set_chat(update)
        if not self.pm or not self.pm.closed_positions:
            await update.message.reply_text("📜 No closed trades yet")
            return

        lines = ["📜 *RECENT TRADES*\n"]
        for pos in self.pm.closed_positions[-10:]:
            emoji = "✅" if pos.pnl >= 0 else "❌"
            combo = getattr(pos, "signal_combo", "?")
            lines.append(
                f"{emoji} {pos.market_name or pos.token_id[:12]}\n"
                f"   {pos.side} | ${pos.pnl:+.2f} | {pos.exit_reason} | {pos.hold_time():.0f}s\n"
                f"   Signals: {combo}\n"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _cmd_signals(self, update, context):
        """🧠 Live detector output for all monitored tokens."""
        self._auto_set_chat(update)
        if not self.signal_engine or not self.orderbook:
            await update.message.reply_text("🧠 Signal engine not connected")
            return

        tokens = list(self.orderbook.get_all_tokens())[:5]  # top 5
        if not tokens:
            await update.message.reply_text("🧠 No tokens being monitored")
            return

        lines = ["🧠 *LIVE SIGNALS*\n"]
        for tid in tokens:
            try:
                sig = self.signal_engine.evaluate(tid, "")
                market = sig.get("market_type", "?")
                lines.append(
                    f"Token: `{tid[:12]}`\n"
                    f"   Whale: {sig['whale_score']:+.2f}\n"
                    f"   Insider: {sig['insider_score']:+.2f}\n"
                    f"   Cluster: {sig['cluster_score']:+.2f}\n"
                    f"   Crypto: {sig['crypto_sentiment']:+.4f}\n"
                    f"   Spoof: {sig['spoof_penalty']:.2f}\n"
                    f"   *Score: {sig['score']:+.3f} → {sig['action']}*\n"
                )
            except Exception:
                continue

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _cmd_whales(self, update, context):
        """🐋 Recent whale activity."""
        self._auto_set_chat(update)
        if not self.whale:
            await update.message.reply_text("🐋 Whale detector not connected")
            return

        # Scan top tokens for whale activity
        tokens = list(self.orderbook.get_all_tokens())[:10] if self.orderbook else []
        lines = ["🐋 *WHALE ACTIVITY*\n"]
        whale_count = 0

        for tid in tokens:
            try:
                result = self.whale.scan(tid)
                if result.get("detected", False):
                    whale_count += 1
                    side = "BULLISH 🟢" if result["score"] > 0 else "BEARISH 🔴"
                    lines.append(
                        f"{side} `{tid[:12]}`\n"
                        f"   Bids: ${result.get('bid_total', 0):,.0f}\n"
                        f"   Asks: ${result.get('ask_total', 0):,.0f}\n"
                    )
            except Exception:
                continue

        if whale_count == 0:
            lines.append("No active whale orders detected right now")
        else:
            lines.append(f"\n*Total: {whale_count} whale positions*")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    # ══════════════════════════════════════════════════════════
    # ANALYTICS (EDGE DISCOVERY)
    # ══════════════════════════════════════════════════════════

    async def _cmd_analytics(self, update, context):
        """📈 Edge discovery breakdown from trade_log.csv."""
        self._auto_set_chat(update)
        log_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "trade_log.csv"
        )
        if not os.path.exists(log_file):
            await update.message.reply_text("📈 No trade data yet — run the bot first")
            return

        try:
            with open(log_file, "r") as f:
                reader = csv.DictReader(f)
                trades = list(reader)
        except Exception:
            await update.message.reply_text("📈 Error reading trade log")
            return

        if not trades:
            await update.message.reply_text("📈 No trades in log yet")
            return

        # ── By signal combo ──────────────────────────────────
        combo_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0})
        type_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0})
        score_buckets = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0})

        for t in trades:
            pnl = float(t.get("pnl", 0))
            combo = t.get("signal_combo", "unknown")
            mtype = t.get("market_type", "general")
            score = abs(float(t.get("signal_score", 0)))

            # Combo stats
            combo_stats[combo]["pnl"] += pnl
            if pnl >= 0:
                combo_stats[combo]["wins"] += 1
            else:
                combo_stats[combo]["losses"] += 1

            # Market type stats
            type_stats[mtype]["pnl"] += pnl
            if pnl >= 0:
                type_stats[mtype]["wins"] += 1
            else:
                type_stats[mtype]["losses"] += 1

            # Score bucket stats
            if score < 0.45:
                bucket = "0.35-0.45"
            elif score < 0.60:
                bucket = "0.45-0.60"
            else:
                bucket = "0.60+"
            score_buckets[bucket]["pnl"] += pnl
            if pnl >= 0:
                score_buckets[bucket]["wins"] += 1
            else:
                score_buckets[bucket]["losses"] += 1

        lines = [f"📈 *EDGE DISCOVERY* ({len(trades)} trades)\n"]

        # By combo
        lines.append("*By Signal Combo:*")
        for combo, s in sorted(combo_stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
            total = s["wins"] + s["losses"]
            wr = f"{s['wins']/total*100:.0f}%" if total > 0 else "N/A"
            emoji = "🟢" if s["pnl"] >= 0 else "🔴"
            lines.append(f"{emoji} {combo} → ${s['pnl']:+.0f} ({wr} win, {total} trades)")

        # By market type
        lines.append("\n*By Market Type:*")
        for mtype, s in sorted(type_stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
            total = s["wins"] + s["losses"]
            wr = f"{s['wins']/total*100:.0f}%" if total > 0 else "N/A"
            emoji = "🟢" if s["pnl"] >= 0 else "🔴"
            lines.append(f"{emoji} {mtype} → ${s['pnl']:+.0f} ({wr}, {total} trades)")

        # By score range
        lines.append("\n*By Score Range:*")
        for bucket in ["0.35-0.45", "0.45-0.60", "0.60+"]:
            if bucket in score_buckets:
                s = score_buckets[bucket]
                total = s["wins"] + s["losses"]
                wr = f"{s['wins']/total*100:.0f}%" if total > 0 else "N/A"
                emoji = "🟢" if s["pnl"] >= 0 else "🔴"
                lines.append(f"{emoji} {bucket} → ${s['pnl']:+.0f} ({wr}, {total} trades)")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    # ══════════════════════════════════════════════════════════
    # CONTROL COMMANDS
    # ══════════════════════════════════════════════════════════

    async def _cmd_pause(self, update, context):
        """⏸ Pause trading (monitoring stays active)."""
        self._auto_set_chat(update)
        self._paused = True
        await update.message.reply_text(
            "⏸ *Trading PAUSED*\n\n"
            "Monitoring still active.\n"
            "Open positions will still be managed.\n"
            "No new trades will be opened.\n\n"
            "Use /resume to restart trading.",
            parse_mode="Markdown",
        )

    async def _cmd_resume(self, update, context):
        """▶️ Resume trading."""
        self._auto_set_chat(update)
        self._paused = False
        await update.message.reply_text(
            "▶️ *Trading RESUMED*\n\n"
            "Bot will now open new positions on valid signals.",
            parse_mode="Markdown",
        )

    # ══════════════════════════════════════════════════════════
    # TUNING COMMANDS
    # ══════════════════════════════════════════════════════════

    async def _cmd_set_confidence(self, update, context):
        """⚙️ Set minimum confidence threshold."""
        self._auto_set_chat(update)
        if not context.args:
            await update.message.reply_text(
                f"Current: {settings.CONFIDENCE_MIN}\nUsage: /set\\_confidence 0.4"
            )
            return
        try:
            val = float(context.args[0])
            if 0.1 <= val <= 1.0:
                settings.CONFIDENCE_MIN = val
                await update.message.reply_text(
                    f"⚙️ Min confidence updated → *{val}*",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text("⚠️ Value must be between 0.1 and 1.0")
        except ValueError:
            await update.message.reply_text("⚠️ Invalid number")

    async def _cmd_set_cooldown(self, update, context):
        """⚙️ Set cooldown seconds."""
        self._auto_set_chat(update)
        if not context.args:
            await update.message.reply_text(
                f"Current: {settings.COOLDOWN_SECONDS}s\nUsage: /set\\_cooldown 30"
            )
            return
        try:
            val = int(context.args[0])
            if 5 <= val <= 300:
                settings.COOLDOWN_SECONDS = val
                await update.message.reply_text(
                    f"⚙️ Cooldown updated → *{val}s*",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text("⚠️ Value must be between 5 and 300")
        except ValueError:
            await update.message.reply_text("⚠️ Invalid number")

    async def _cmd_set_max_positions(self, update, context):
        """⚙️ Set max open positions."""
        self._auto_set_chat(update)
        if not context.args:
            await update.message.reply_text(
                f"Current: {settings.MAX_OPEN_POSITIONS}\nUsage: /set\\_max\\_positions 3"
            )
            return
        try:
            val = int(context.args[0])
            if 1 <= val <= 10:
                settings.MAX_OPEN_POSITIONS = val
                await update.message.reply_text(
                    f"⚙️ Max positions updated → *{val}*",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text("⚠️ Value must be between 1 and 10")
        except ValueError:
            await update.message.reply_text("⚠️ Invalid number")

    # ══════════════════════════════════════════════════════════
    # HELPERS
    # ══════════════════════════════════════════════════════════

    def _auto_set_chat(self, update):
        """Auto-detect chat ID from incoming messages."""
        if not self._chat_id and update.effective_chat:
            self._chat_id = str(update.effective_chat.id)
            log.info(f"Auto-detected chat ID: {self._chat_id}")

    async def stop(self):
        if self._app:
            try:
                await self.send("🛑 *Bot shutting down...*")
                await self._app.updater.stop()
                await self._app.stop()
                await self._app.shutdown()
            except Exception:
                pass
