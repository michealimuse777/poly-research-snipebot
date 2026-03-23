"""
Polymarket Whale + Insider Snipe Bot
=====================================
Detects whale activity, insider flow, wallet clusters, and crypto market context
to snipe prediction market entries before price adjusts.

Usage:
    python main.py              # Paper trade (default)
    python main.py --paper      # Paper trade (explicit)
    python main.py --live       # Live trade (requires API keys)
    python main.py --no-telegram  # Disable Telegram
"""
import argparse
import asyncio
import os
import signal
import sys
import time

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import settings
from utils.logger import get_logger

# Data layer
from stream.ws_client import PolymarketWSClient
from stream.orderbook_cache import OrderbookCache
from stream.trade_feed import TradeFeed
from data.crypto_feed import CryptoFeed
from data.market_fetcher import fetch_top_markets, get_all_token_ids, get_token_to_market_map

# Detectors
from detectors.whale_detector import WhaleDetector
from detectors.insider_detector import InsiderDetector
from detectors.cluster_detector import ClusterDetector
from detectors.spoofing_detector import SpoofingDetector
from detectors.crypto_context import CryptoContext

# Engine
from engine.signal_engine import SignalEngine
from engine.snipe_executor import SnipeExecutor
from engine.exit_engine import ExitEngine
from engine.position_manager import PositionManager

# Telegram
from telegram.bot import TelegramNotifier

log = get_logger("main")

BANNER = r"""
╔══════════════════════════════════════════════════════════╗
║    🐋  POLYMARKET WHALE + INSIDER SNIPE BOT  🐋        ║
║    ──────────────────────────────────────────            ║
║    Whale Detection · Insider Flow · Crypto Context      ║
║    Wallet Clusters · Spoofing Filter · Fast Exits       ║
╚══════════════════════════════════════════════════════════╝
"""


class SnipeBot:
    """Main snipe bot orchestrator."""

    def __init__(self, mode: str = "paper", use_telegram: bool = True):
        self.mode = mode
        self.use_telegram = use_telegram
        self._running = False
        self.cycle_count = 0

        # ── Data Layer ──────────────────────────────────────
        self.orderbook = OrderbookCache()
        self.trade_feed = TradeFeed()
        self.crypto_feed = CryptoFeed()
        self.ws_client = PolymarketWSClient()

        # ── Detectors ───────────────────────────────────────
        self.whale_detector = WhaleDetector(self.orderbook)
        self.insider_detector = InsiderDetector(self.trade_feed)
        self.cluster_detector = ClusterDetector(self.trade_feed)
        self.spoofing_detector = SpoofingDetector()
        self.crypto_context = CryptoContext(self.crypto_feed)

        # ── Engine ──────────────────────────────────────────
        self.signal_engine = SignalEngine(
            whale=self.whale_detector,
            insider=self.insider_detector,
            cluster=self.cluster_detector,
            spoofing=self.spoofing_detector,
            crypto=self.crypto_context,
        )
        self.position_manager = PositionManager()
        self.snipe_executor = SnipeExecutor(
            signal_engine=self.signal_engine,
            position_manager=self.position_manager,
            orderbook=self.orderbook,
        )
        self.exit_engine = ExitEngine(self.position_manager, self.orderbook, self.signal_engine)

        # ── Telegram ────────────────────────────────────────
        self.telegram = TelegramNotifier(
            position_manager=self.position_manager,
            snipe_executor=self.snipe_executor,
            signal_engine=self.signal_engine,
            whale_detector=self.whale_detector,
            spoofing_detector=self.spoofing_detector,
            orderbook=self.orderbook,
        ) if use_telegram else None

        # Market data
        self.markets: list[dict] = []
        self.token_ids: list[str] = []
        self.token_to_market: dict[str, str] = {}

    async def start(self):
        """Start the snipe bot."""
        print(BANNER)
        log.info(f"Mode: {'📝 PAPER TRADE' if self.mode == 'paper' else '💰 LIVE TRADE'}")
        log.info(f"Bankroll: ${settings.STARTING_BANKROLL:,.2f}")
        log.info(f"Whale threshold: ${settings.WHALE_THRESHOLD:,.0f}")
        log.info(f"TP: {settings.TAKE_PROFIT*100:.1f}% | SL: {settings.STOP_LOSS*100:.1f}% | Time: {settings.TIME_EXIT_SECONDS}s")
        log.info(f"Max positions: {settings.MAX_OPEN_POSITIONS} | Size: {settings.POSITION_SIZE_PCT*100:.0f}% bankroll")

        self._running = True

        # ── 1. Fetch markets ────────────────────────────────
        log.info("Fetching top markets by volume...")
        self.markets = fetch_top_markets()
        if not self.markets:
            log.error("No markets fetched — exiting")
            return

        self.token_ids = get_all_token_ids(self.markets)
        self.token_to_market = get_token_to_market_map(self.markets)
        log.info(f"Monitoring {len(self.token_ids)} tokens across {len(self.markets)} markets")

        # ── 2. Register WebSocket callbacks ─────────────────
        self.ws_client.on_orderbook(self._handle_orderbook)
        self.ws_client.on_trade(self._handle_trade)

        # Wire orderbook synthetic trades → trade feed
        # When order sizes drop (fills), the orderbook generates synthetic trades
        self.orderbook.on_synthetic_trade(
            lambda token_id, price, size, side: self.trade_feed.add_trade(
                token_id, price, size, side
            )
        )

        # ── 3. Start all tasks ──────────────────────────────
        tasks = [
            asyncio.create_task(self.ws_client.connect(self.token_ids)),
            asyncio.create_task(self.crypto_feed.start()),
            asyncio.create_task(self._main_loop()),
            asyncio.create_task(self._exit_loop()),
            asyncio.create_task(self._maintenance_loop()),
        ]

        if self.telegram and self.use_telegram:
            tasks.append(asyncio.create_task(self.telegram.start()))

        log.info("🚀 All systems online — snipe bot running")

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            log.info("Bot shutting down...")

    def _handle_orderbook(self, token_id: str, bids: list, asks: list):
        """WebSocket callback: update orderbook cache + track spoofing."""
        self.orderbook.update(token_id, bids, asks)

        # Track whale-sized orders for spoofing detection
        for bid in bids:
            price = float(bid.get("price", bid.get("p", 0)))
            size = float(bid.get("size", bid.get("s", 0)))
            self.spoofing_detector.track_order(token_id, price, size)

        for ask in asks:
            price = float(ask.get("price", ask.get("p", 0)))
            size = float(ask.get("size", ask.get("s", 0)))
            self.spoofing_detector.track_order(token_id, price, size)

    def _handle_trade(self, token_id: str, price: float, size: float, side: str, ts: str):
        """WebSocket callback: record trade in feed."""
        self.trade_feed.add_trade(token_id, price, size, side, ts)

    async def _main_loop(self):
        """Main snipe evaluation loop — runs every 500ms."""
        # Wait for data to arrive
        await asyncio.sleep(5)
        log.info("⚡ Main snipe loop started")

        while self._running:
            try:
                self.cycle_count += 1

                # Check pause state from Telegram
                if self.telegram and self.telegram.is_paused:
                    await asyncio.sleep(1)
                    continue

                # Scan all active tokens for snipe opportunities
                entries_this_cycle = 0
                for token_id in self.orderbook.get_all_tokens():
                    market_name = self.token_to_market.get(token_id, "")
                    pos = self.snipe_executor.evaluate(token_id, market_name)

                    if pos and self.mode == "paper":
                        entries_this_cycle += 1
                        # Telegram alert with full signal data
                        if self.telegram:
                            await self.telegram.alert_entry(
                                side=pos.side,
                                market=pos.market_name,
                                price=pos.entry_price,
                                score=getattr(pos, 'signal_score', 0.0),
                                size=pos.size,
                                combo=getattr(pos, 'signal_combo', ''),
                                market_type=getattr(pos, 'market_type', ''),
                                tp=getattr(pos, 'dynamic_tp', settings.TAKE_PROFIT),
                                sl=getattr(pos, 'dynamic_sl', settings.STOP_LOSS),
                            )

                # Periodic status log
                if self.cycle_count % 60 == 0:  # every 30s
                    stats = self.position_manager.get_stats()
                    log.info(
                        f"📊 Cycle {self.cycle_count} | "
                        f"Tokens: {len(self.orderbook.get_all_tokens())} | "
                        f"Trades in feed: {self.trade_feed.total_trades} | "
                        f"Open: {stats['open_positions']} | "
                        f"PnL: ${stats['total_pnl']:+.2f} | "
                        f"Bankroll: ${stats['bankroll']:,.2f}"
                    )

            except Exception as e:
                log.error(f"Main loop error: {e}")

            await asyncio.sleep(settings.CYCLE_INTERVAL)

    async def _exit_loop(self):
        """Exit monitoring loop — checks every 500ms for TP/SL/time exits."""
        await asyncio.sleep(8)
        log.info("🛑 Exit engine started")

        while self._running:
            try:
                # Get positions before exit check for alerting
                open_before = set(self.position_manager.open_positions.keys())
                self.exit_engine.check_exits()
                open_after = set(self.position_manager.open_positions.keys())

                # Alert on any closed positions
                closed = open_before - open_after
                for tid in closed:
                    # Find the closed position in history
                    for pos in reversed(self.position_manager.closed_positions):
                        if pos.token_id == tid:
                            if self.telegram:
                                pnl_pct = (pos.pnl / pos.size * 100) if pos.size else 0
                                await self.telegram.alert_exit(
                                    pos.side, pos.market_name, pos.pnl,
                                    pos.exit_reason, pos.hold_time(),
                                    pnl_pct=pnl_pct,
                                )
                            break

            except Exception as e:
                log.error(f"Exit loop error: {e}")

            await asyncio.sleep(settings.EXIT_CHECK_INTERVAL)

    async def _maintenance_loop(self):
        """Periodic cleanup — decay spoofing counts, refresh markets."""
        await asyncio.sleep(30)

        while self._running:
            try:
                # Decay spoofing counters
                self.spoofing_detector.decay()
                self.spoofing_detector.cleanup()

                # Refresh markets every 5 minutes
                if self.cycle_count % 600 == 0:
                    log.info("🔄 Refreshing market list...")
                    self.markets = fetch_top_markets()
                    new_tokens = get_all_token_ids(self.markets)
                    self.token_to_market = get_token_to_market_map(self.markets)

                    # Subscribe to any new tokens
                    new_set = set(new_tokens) - set(self.token_ids)
                    if new_set:
                        log.info(f"Found {len(new_set)} new tokens to monitor")
                        self.token_ids = new_tokens

            except Exception as e:
                log.error(f"Maintenance error: {e}")

            await asyncio.sleep(30)

    async def stop(self):
        """Gracefully shutdown."""
        self._running = False
        log.info("Shutting down...")

        await self.ws_client.stop()
        await self.crypto_feed.stop()

        if self.telegram:
            stats = self.position_manager.get_stats()
            await self.telegram.send(
                f"🛑 *Bot Stopping*\n"
                f"PnL: ${stats['total_pnl']:+.2f}\n"
                f"Trades: {stats['total_trades']}\n"
                f"Win rate: {stats['win_rate']}"
            )
            await self.telegram.stop()

        log.info("All systems offline")


def main():
    parser = argparse.ArgumentParser(description="Polymarket Whale + Insider Snipe Bot")
    parser.add_argument("--paper", action="store_true", default=True, help="Paper trade mode (default)")
    parser.add_argument("--live", action="store_true", help="Live trade mode")
    parser.add_argument("--no-telegram", action="store_true", help="Disable Telegram")
    args = parser.parse_args()

    mode = "live" if args.live else "paper"
    use_telegram = not args.no_telegram

    bot = SnipeBot(mode=mode, use_telegram=use_telegram)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Handle Ctrl+C
    def shutdown(sig, frame):
        log.info("Caught interrupt — stopping...")
        loop.create_task(bot.stop())

    signal.signal(signal.SIGINT, shutdown)

    try:
        loop.run_until_complete(bot.start())
    except KeyboardInterrupt:
        loop.run_until_complete(bot.stop())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
