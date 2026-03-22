"""
Market Fetcher — gets top Polymarket markets by volume to monitor.
"""
import requests

import settings
from utils.logger import get_logger

log = get_logger("markets")


def fetch_top_markets(limit: int = None) -> list[dict]:
    """
    Fetch the top markets by volume from Polymarket's Gamma API.

    Returns list of:
        {
            "condition_id": str,
            "question": str,
            "tokens": [{"token_id": str, "outcome": str}, ...],
            "volume": float,
        }
    """
    limit = limit or settings.TOP_MARKETS_COUNT

    try:
        url = f"{settings.GAMMA_API}/markets"
        params = {
            "closed": "false",
            "limit": limit,
            "order": "volume24hr",
            "ascending": "false",
        }
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        raw_markets = resp.json()

        markets = []
        for m in raw_markets:
            tokens = m.get("clobTokenIds", "")
            if isinstance(tokens, str):
                tokens = [t.strip() for t in tokens.strip("[]").replace('"', '').split(",") if t.strip()]

            outcomes = m.get("outcomes", "")
            if isinstance(outcomes, str):
                outcomes = [o.strip() for o in outcomes.strip("[]").replace('"', '').split(",") if o.strip()]

            token_list = []
            for i, tid in enumerate(tokens):
                outcome = outcomes[i] if i < len(outcomes) else f"Token{i}"
                token_list.append({"token_id": tid, "outcome": outcome})

            markets.append({
                "condition_id": m.get("conditionId", ""),
                "question": m.get("question", "Unknown"),
                "tokens": token_list,
                "volume": float(m.get("volume24hr", 0) or 0),
            })

        log.info(f"Fetched {len(markets)} top markets by volume")
        return markets

    except Exception as e:
        log.error(f"Failed to fetch markets: {e}")
        return []


def get_all_token_ids(markets: list[dict]) -> list[str]:
    """Extract all token IDs from market list."""
    tokens = []
    for m in markets:
        for t in m.get("tokens", []):
            tid = t.get("token_id", "")
            if tid:
                tokens.append(tid)
    return tokens


def get_token_to_market_map(markets: list[dict]) -> dict[str, str]:
    """Map token_id → market question for display purposes."""
    mapping = {}
    for m in markets:
        for t in m.get("tokens", []):
            tid = t.get("token_id", "")
            if tid:
                mapping[tid] = m.get("question", "Unknown")
    return mapping
