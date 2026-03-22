"""
Crypto price feed — BTC/ETH/SOL via CoinCap REST API.
Polls every 15 seconds. Falls back to CoinGecko if CoinCap fails.
No API key needed for either.
"""
import asyncio
import time
from collections import deque

import requests

from utils.logger import get_logger

log = get_logger("crypto_feed")

WINDOW_SIZE = 300

ASSETS = {
    "bitcoin": "btcusdt",
    "ethereum": "ethusdt",
    "solana": "solusdt",
}

COINCAP_URL = "https://api.coincap.io/v2/assets"
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"


class CryptoFeed:
    """Crypto price polling from CoinCap REST API (with CoinGecko fallback)."""

    def __init__(self):
        self.prices: dict[str, float] = {}
        self.history: dict[str, deque] = {}
        self._running = False
        self._fetch_count = 0

        for pair in ASSETS.values():
            self.prices[pair] = 0.0
            self.history[pair] = deque(maxlen=WINDOW_SIZE)

    async def start(self):
        """Poll crypto prices every 15 seconds."""
        self._running = True
        log.info("📊 Crypto feed starting (CoinCap REST)...")

        # Initial fetch
        await self._fetch()

        while self._running:
            try:
                await asyncio.sleep(15)
                await self._fetch()
            except Exception as e:
                log.error(f"Crypto poll error: {e}")
                await asyncio.sleep(30)

    async def _fetch(self):
        """Fetch prices — try CoinCap first, fall back to CoinGecko."""
        success = await self._fetch_coincap()
        if not success:
            await self._fetch_coingecko()

    async def _fetch_coincap(self) -> bool:
        """Fetch from CoinCap REST API."""
        try:
            ids = ",".join(ASSETS.keys())
            resp = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: requests.get(f"{COINCAP_URL}?ids={ids}", timeout=10),
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])

            now = time.time()
            for asset in data:
                asset_id = asset.get("id", "").lower()
                price = float(asset.get("priceUsd", 0))
                pair_key = ASSETS.get(asset_id)

                if pair_key and price > 0:
                    self.prices[pair_key] = price
                    self.history[pair_key].append({"price": price, "time": now})

            self._fetch_count += 1
            if self._fetch_count % 4 == 1:  # log every ~60s
                btc = self.prices.get("btcusdt", 0)
                eth = self.prices.get("ethusdt", 0)
                sol = self.prices.get("solusdt", 0)
                log.info(f"📊 BTC=${btc:,.0f} ETH=${eth:,.0f} SOL=${sol:,.2f}")
            return True

        except Exception as e:
            log.warning(f"CoinCap failed: {e}, trying CoinGecko...")
            return False

    async def _fetch_coingecko(self) -> bool:
        """Fallback to CoinGecko."""
        try:
            coin_ids = ",".join(ASSETS.keys())
            params = {"ids": coin_ids, "vs_currencies": "usd"}

            resp = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: requests.get(COINGECKO_URL, params=params, timeout=10),
            )
            resp.raise_for_status()
            data = resp.json()

            now = time.time()
            for gecko_id, pair_key in ASSETS.items():
                price = data.get(gecko_id, {}).get("usd", 0)
                if price > 0:
                    self.prices[pair_key] = float(price)
                    self.history[pair_key].append({"price": float(price), "time": now})

            return True
        except Exception as e:
            log.error(f"CoinGecko also failed: {e}")
            return False

    def get_price(self, pair: str) -> float:
        return self.prices.get(pair.lower(), 0.0)

    def get_prices_window(self, pair: str) -> list[float]:
        if pair not in self.history:
            return []
        return [p["price"] for p in self.history[pair]]

    def get_all_prices(self) -> dict[str, float]:
        return dict(self.prices)

    async def stop(self):
        self._running = False
        log.info("Crypto feed stopped")
