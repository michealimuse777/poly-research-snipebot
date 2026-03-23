"""
Signal Engine — the brain of the snipe bot.
Combines whale, insider, cluster, spoofing, and crypto context scores
into a single actionable BUY/SELL/HOLD signal.

KEY RULES:
  1. At least 2 detectors must agree (multi-signal requirement)
  2. Spoofing blocks trades (not just logs)
  3. Cluster = supporting only (never trade on cluster alone)
  4. High confidence threshold (0.35+)
  5. Market-type aware: crypto vs sports use different weights
"""
import settings
from detectors.whale_detector import WhaleDetector
from detectors.insider_detector import InsiderDetector
from detectors.cluster_detector import ClusterDetector
from detectors.spoofing_detector import SpoofingDetector
from detectors.crypto_context import CryptoContext
from utils.logger import get_logger

log = get_logger("signal")


def classify_market(market_name: str) -> str:
    """Classify market as 'crypto', 'sports', or 'general'."""
    name = market_name.lower()
    for kw in settings.CRYPTO_KEYWORDS:
        if kw in name:
            return "crypto"
    for kw in settings.SPORTS_KEYWORDS:
        if kw in name:
            return "sports"
    return "general"


class SignalEngine:
    """Combine all detector outputs into a single actionable signal."""

    def __init__(
        self,
        whale: WhaleDetector,
        insider: InsiderDetector,
        cluster: ClusterDetector,
        spoofing: SpoofingDetector,
        crypto: CryptoContext,
    ):
        self.whale = whale
        self.insider = insider
        self.cluster = cluster
        self.spoofing = spoofing
        self.crypto = crypto
        self.signal_count = 0
        self.blocked_count = 0

    def evaluate(self, token_id: str, market_name: str = "") -> dict:
        """
        Run all detectors and produce a composite signal.
        SELECTIVE — only fires on strong, multi-signal setups.
        """
        # ── Classify market type ─────────────────────────────
        market_type = classify_market(market_name)

        # ── Run detectors ───────────────────────────────────
        whale_result = self.whale.scan(token_id)
        insider_result = self.insider.scan(token_id)
        cluster_result = self.cluster.scan(token_id)
        crypto_result = self.crypto.analyze()

        whale_score = whale_result["score"]
        insider_score = insider_result["score"]
        cluster_score = cluster_result["score"]
        crypto_score = crypto_result["sentiment"]
        lead_lag = crypto_result["lead_lag_signal"]

        # ── Spoofing check — BLOCK if heavy spoofing ────────
        spoof_penalty = self.spoofing.get_penalty(token_id)
        if spoof_penalty >= settings.SPOOF_BLOCK_PENALTY:
            self.blocked_count += 1
            if self.blocked_count % 10 == 1:
                log.warning(
                    f"🚫 BLOCKED by spoofing | {token_id[:8]}... | "
                    f"penalty={spoof_penalty:.2f}"
                )
            return self._hold_result(
                whale_score, insider_score, cluster_score,
                crypto_score, spoof_penalty, lead_lag,
                "spoof_blocked", market_type
            )

        # ── Reduce whale signal by spoof penalty ────────────
        whale_adjusted = whale_score * (1.0 - spoof_penalty)

        # ── Market-type aware weights ────────────────────────
        if market_type == "crypto":
            # Crypto markets: crypto context dominates
            w_whale = 0.20
            w_insider = 0.20
            w_cluster = 0.05
            w_crypto = 0.45
            w_flow = 0.10
        elif market_type == "sports":
            # Sports: ignore crypto, rely on flow/whales
            w_whale = 0.40
            w_insider = 0.30
            w_cluster = 0.10
            w_crypto = 0.0  # crypto is irrelevant for sports
            w_flow = 0.20
        else:
            # General: balanced
            w_whale = settings.W_WHALE
            w_insider = settings.W_INSIDER
            w_cluster = settings.W_CLUSTER
            w_crypto = settings.W_CRYPTO
            w_flow = settings.W_FLOW

        # ── Multi-signal requirement ─────────────────────────
        active_signals = 0
        signal_direction = 0
        active_detectors = []  # track which detectors fired for logging

        if abs(whale_adjusted) > 0.1:
            active_signals += 1
            signal_direction += 1 if whale_adjusted > 0 else -1
            active_detectors.append("whale")

        if abs(insider_score) > 0.1:
            active_signals += 1
            signal_direction += 1 if insider_score > 0 else -1
            active_detectors.append("insider")

        # Crypto only counts for non-sports markets
        if abs(crypto_score) > 0.002 and market_type != "sports":
            active_signals += 1
            signal_direction += 1 if crypto_score > 0 else -1
            active_detectors.append("crypto")

        # Cluster supports but doesn't trigger by itself
        cluster_aligns = (
            (cluster_score > 0.1 and signal_direction > 0) or
            (cluster_score < -0.1 and signal_direction < 0)
        )
        if cluster_aligns:
            active_detectors.append("cluster")

        signals_agree = abs(signal_direction) >= settings.MIN_SIGNALS_REQUIRED
        enough_signals = active_signals >= settings.MIN_SIGNALS_REQUIRED

        # ── Composite score ─────────────────────────────────
        flow_score = (insider_score + cluster_score) / 2.0

        score = (
            whale_adjusted * w_whale +
            insider_score * w_insider +
            cluster_score * w_cluster +
            flow_score * w_flow +
            crypto_score * w_crypto
        )

        # Lead-lag bonus (only if signals already agree, not sports)
        if abs(lead_lag) > 0.005 and signals_agree and market_type != "sports":
            score += lead_lag * 0.1

        # Cluster alignment bonus
        if cluster_aligns:
            score *= 1.15

        confidence = abs(score)

        # ── Decision (SELECTIVE) ─────────────────────────────
        action = "HOLD"
        block_reason = ""

        if confidence < settings.CONFIDENCE_MIN:
            block_reason = "low_confidence"
        elif not enough_signals:
            block_reason = "insufficient_signals"
        elif not signals_agree:
            block_reason = "signals_disagree"
        elif score >= settings.SIGNAL_BUY_THRESHOLD:
            action = "BUY"
        elif score <= settings.SIGNAL_SELL_THRESHOLD:
            action = "SELL"

        # Build signal combo string for CSV logging (before gating checks)
        signal_combo = "+".join(active_detectors) if active_detectors else "none"

        # ── Sports markets gate: require stronger signals ────
        # Sports were 33% WR, -$653. Need score>0.55 or 3+ active detectors
        if action != "HOLD" and market_type == "sports":
            if confidence < 0.55 and len(active_detectors) < 3:
                action = "HOLD"
                block_reason = "sports_weak_signal"

        # ── whale+insider only gate: bump min confidence ─────
        # whale+insider alone was 35% WR, -$784. Require higher bar
        if action != "HOLD" and signal_combo == "whale+insider":
            if confidence < 0.45:
                action = "HOLD"
                block_reason = "wi_low_confidence"

        result = {
            "action": action,
            "score": round(score, 4),
            "confidence": round(confidence, 4),
            "whale_score": round(whale_adjusted, 4),
            "insider_score": round(insider_score, 4),
            "cluster_score": round(cluster_score, 4),
            "crypto_sentiment": round(crypto_score, 6),
            "spoof_penalty": round(spoof_penalty, 2),
            "lead_lag": round(lead_lag, 4),
            "active_signals": active_signals,
            "signals_agree": signals_agree,
            "cluster_aligns": cluster_aligns,
            "block_reason": block_reason,
            "market_type": market_type,
            "signal_combo": signal_combo,
            "tradeable": True,
        }

        if action != "HOLD":
            self.signal_count += 1
            emoji = "🟢 BUY" if action == "BUY" else "🔴 SELL"
            log.info(
                f"⚡ SIGNAL #{self.signal_count} {emoji} | "
                f"{market_name[:30] if market_name else token_id[:8]} | "
                f"type={market_type} | "
                f"score={score:+.3f} conf={confidence:.3f} | "
                f"combo={signal_combo} | "
                f"🐋{whale_adjusted:+.2f} 🕵️{insider_score:+.2f} "
                f"🔗{cluster_score:+.2f} 📊{crypto_score:+.4f}"
            )

        return result

    def _hold_result(self, whale, insider, cluster, crypto, spoof, lead_lag, reason, market_type=""):
        return {
            "action": "HOLD",
            "score": 0.0,
            "confidence": 0.0,
            "whale_score": round(whale, 4),
            "insider_score": round(insider, 4),
            "cluster_score": round(cluster, 4),
            "crypto_sentiment": round(crypto, 6),
            "spoof_penalty": round(spoof, 2),
            "lead_lag": round(lead_lag, 4),
            "active_signals": 0,
            "signals_agree": False,
            "cluster_aligns": False,
            "block_reason": reason,
            "market_type": market_type,
            "signal_combo": "none",
            "tradeable": False,
        }
