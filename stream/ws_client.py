"""
Async WebSocket client for Polymarket CLOB.
Streams live price changes from the market channel.

Also polls CLOB REST API for recent trades (WS doesn't stream individual trades).
"""
import asyncio
import json
import time
from typing import Callable, Optional

import requests
import websockets

import settings
from utils.logger import get_logger

log = get_logger("ws_client")


class PolymarketWSClient:
    """Connects to Polymarket WebSocket and dispatches orderbook/trade events."""

    def __init__(self):
        self.url = settings.POLYMARKET_WS
        self._ws = None
        self._subscribed_tokens: list[str] = []
        self._on_orderbook: Optional[Callable] = None
        self._on_trade: Optional[Callable] = None
        self._running = False
        self._msg_count = 0
        self._event_count = 0

    def on_orderbook(self, callback: Callable):
        """Register callback: callback(token_id, bids, asks)."""
        self._on_orderbook = callback

    def on_trade(self, callback: Callable):
        """Register callback: callback(token_id, price, size, side, timestamp)."""
        self._on_trade = callback

    async def connect(self, token_ids: list[str]):
        """Connect, subscribe, and start trade polling."""
        self._subscribed_tokens = token_ids
        self._running = True

        # Run WS stream and trade poller in parallel
        await asyncio.gather(
            self._ws_loop(token_ids),
            self._trade_poller(token_ids),
        )

    async def _ws_loop(self, token_ids: list[str]):
        """WebSocket connection loop with auto-reconnect."""
        while self._running:
            try:
                async with websockets.connect(self.url, ping_interval=20, ping_timeout=10) as ws:
                    self._ws = ws
                    log.info("⚡ WebSocket connected to Polymarket CLOB")
                    await self._subscribe(ws, token_ids)
                    await self._listen(ws)
            except websockets.ConnectionClosed:
                log.warning("WebSocket disconnected. Reconnecting in 3s...")
                await asyncio.sleep(3)
            except Exception as e:
                log.error(f"WebSocket error: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)

    async def _subscribe(self, ws, token_ids: list[str]):
        """Subscribe to market channel for all tokens."""
        batch_size = 50
        for i in range(0, len(token_ids), batch_size):
            batch = token_ids[i : i + batch_size]
            sub = {"type": "market", "assets_ids": batch}
            await ws.send(json.dumps(sub))
            if i + batch_size < len(token_ids):
                await asyncio.sleep(0.1)
        log.info(f"Subscribed to {len(token_ids)} tokens")

    async def _listen(self, ws):
        """Listen and dispatch events."""
        async for raw in ws:
            try:
                msg = json.loads(raw)
                self._msg_count += 1

                # Debug first 3 messages
                if self._msg_count <= 3:
                    log.info(f"📨 WS msg #{self._msg_count} ({type(msg).__name__}): {str(raw)[:120]}...")

                if isinstance(msg, list):
                    for item in msg:
                        if isinstance(item, dict):
                            self._process_event(item)
                elif isinstance(msg, dict):
                    self._process_event(msg)

            except json.JSONDecodeError:
                continue
            except Exception as e:
                log.error(f"WS handler error: {e}")

    def _process_event(self, event: dict):
        """Process a market event — extract price changes as orderbook updates."""
        price_changes = event.get("price_changes", [])

        for change in price_changes:
            if not isinstance(change, dict):
                continue

            asset_id = change.get("asset_id", "")
            price_str = change.get("price", "0")
            size_str = change.get("size", "0")

            if not asset_id:
                continue

            try:
                price = float(price_str)
                size = float(size_str)
            except (ValueError, TypeError):
                continue

            if price <= 0:
                continue

            self._event_count += 1

            # Classify as bid or ask based on price: <=0.5 = bid, >0.5 = ask
            # (In prediction markets, low price = buying cheap = bid side)
            entry = {"price": price, "size": size}
            if price <= 0.50:
                bids = [entry]
                asks = []
            else:
                bids = []
                asks = [entry]

            if self._on_orderbook:
                try:
                    result = self._on_orderbook(asset_id, bids, asks)
                    if asyncio.iscoroutine(result):
                        asyncio.ensure_future(result)
                except Exception:
                    pass

        # Log periodically
        if self._event_count > 0 and self._event_count % 500 == 0:
            log.info(f"📡 {self._event_count} price events | {self._msg_count} WS msgs")

    # ── Trade Polling ───────────────────────────────────────────

    async def _trade_poller(self, token_ids: list[str]):
        """Poll CLOB REST API for recent trades every 5 seconds."""
        await asyncio.sleep(5)  # wait for WS to connect first
        log.info("📊 Trade poller started")

        # Track seen trade IDs to avoid duplicates
        seen_trades: set[str] = set()

        while self._running:
            try:
                trades = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self._fetch_trades()
                )

                new_count = 0
                for t in trades:
                    trade_id = t.get("id", "")
                    if trade_id in seen_trades:
                        continue
                    seen_trades.add(trade_id)
                    new_count += 1

                    asset_id = t.get("asset_id", "")
                    price = float(t.get("price", 0))
                    size = float(t.get("size", 0))
                    side = t.get("side", t.get("type", ""))
                    ts = t.get("match_time", t.get("created_at", ""))

                    if asset_id and price > 0 and size > 0 and self._on_trade:
                        try:
                            result = self._on_trade(asset_id, price, size, side, ts)
                            if asyncio.iscoroutine(result):
                                asyncio.ensure_future(result)
                        except Exception:
                            pass

                if new_count > 0:
                    log.info(f"📊 {new_count} new trades from CLOB API")

                # Cap seen_trades size
                if len(seen_trades) > 10000:
                    seen_trades = set(list(seen_trades)[-5000:])

            except Exception as e:
                log.error(f"Trade poll error: {e}")

            await asyncio.sleep(5)

    def _fetch_trades(self) -> list[dict]:
        """Fetch recent trades from Gamma API (public, no auth needed)."""
        try:
            resp = requests.get(
                f"{settings.GAMMA_API}/activity",
                params={"limit": 50, "type": "trade"},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data if isinstance(data, list) else []
            return []
        except Exception:
            return []

    async def stop(self):
        self._running = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            log.info("WebSocket closed")
