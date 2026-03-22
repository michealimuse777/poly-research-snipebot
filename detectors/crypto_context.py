"""
Crypto Context Engine — BTC/ETH/SOL momentum, sentiment, volatility, and lead-lag detection.
Polymarket prices are heavily influenced by crypto market conditions.
This engine provides market context that gives the sniper a predictive edge.
"""
import numpy as np

import settings
from data.crypto_feed import CryptoFeed
from utils.logger import get_logger

log = get_logger("crypto_ctx")


class CryptoContext:
    """Analyze crypto market conditions to enhance snipe signals."""

    def __init__(self, feed: CryptoFeed):
        self.feed = feed

    def analyze(self) -> dict:
        """
        Full crypto market analysis.

        Returns:
            {
                "sentiment": float,         # weighted BTC/ETH/SOL momentum (-1 to 1)
                "btc_momentum": float,      # BTC short-term momentum
                "eth_momentum": float,
                "sol_momentum": float,
                "volatility": float,        # market volatility (std of returns)
                "lead_lag_signal": float,    # crypto moved but poly hasn't = opportunity
                "risk_on": bool,            # is market risk-on?
                "tradeable": bool,          # enough volatility to trade?
            }
        """
        btc_mom = self._momentum("btcusdt")
        eth_mom = self._momentum("ethusdt")
        sol_mom = self._momentum("solusdt")

        # Weighted sentiment: BTC dominates
        sentiment = btc_mom * 0.5 + eth_mom * 0.3 + sol_mom * 0.2

        # Volatility from BTC (market leader)
        volatility = self._volatility("btcusdt")

        # Lead-lag: are we seeing a big crypto move?
        lead_lag = self._lead_lag_signal()

        risk_on = sentiment > 0.005
        tradeable = volatility >= settings.VOLATILITY_MIN

        result = {
            "sentiment": round(sentiment, 6),
            "btc_momentum": round(btc_mom, 6),
            "eth_momentum": round(eth_mom, 6),
            "sol_momentum": round(sol_mom, 6),
            "volatility": round(volatility, 6),
            "lead_lag_signal": round(lead_lag, 4),
            "risk_on": risk_on,
            "tradeable": tradeable,
        }

        return result

    def _momentum(self, pair: str) -> float:
        """Calculate short-term price momentum: (last - first) / first."""
        prices = self.feed.get_prices_window(pair)
        if len(prices) < 10:
            return 0.0
        return (prices[-1] - prices[0]) / prices[0]

    def _volatility(self, pair: str) -> float:
        """Calculate volatility as std of returns."""
        prices = self.feed.get_prices_window(pair)
        if len(prices) < 10:
            return 0.0
        prices_arr = np.array(prices)
        returns = np.diff(prices_arr) / prices_arr[:-1]
        return float(np.std(returns))

    def _lead_lag_signal(self) -> float:
        """
        Detect crypto spike — if BTC moved significantly in the last minute,
        this creates a lead-lag opportunity on Polymarket.

        Returns directional signal: positive = crypto bullish, negative = bearish.
        """
        prices = self.feed.get_prices_window("btcusdt")
        if len(prices) < 20:
            return 0.0

        # Compare last 20 data points (recent) vs last 60 (older)
        recent = prices[-20:]
        older = prices[-60:-20] if len(prices) >= 60 else prices[:len(prices) - 20]

        if not older:
            return 0.0

        recent_avg = sum(recent) / len(recent)
        older_avg = sum(older) / len(older)

        move = (recent_avg - older_avg) / older_avg

        # Only signal if move is meaningful (> 0.5%)
        if abs(move) > 0.005:
            return move
        return 0.0
