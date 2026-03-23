"""
Polymarket Whale + Insider Snipe Bot — Configuration
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Polymarket ──────────────────────────────────────────────
POLYMARKET_WS  = os.getenv("POLYMARKET_WS", "wss://ws-subscriptions-clob.polymarket.com/ws/market")
GAMMA_API      = os.getenv("GAMMA_API", "https://gamma-api.polymarket.com")
CLOB_API       = os.getenv("CLOB_API", "https://clob.polymarket.com")

# ── CoinCap (crypto context) ───────────────────────────────
COINCAP_WS     = os.getenv("COINCAP_WS", "wss://ws.coincap.io/prices?assets=bitcoin,ethereum,solana")

# ── Redis ───────────────────────────────────────────────────
REDIS_HOST     = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT     = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

# ── PostgreSQL ──────────────────────────────────────────────
POSTGRES_HOST  = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT  = int(os.getenv("POSTGRES_PORT", 5432))
POSTGRES_DB    = os.getenv("POSTGRES_DB", "snipebot")
POSTGRES_USER  = os.getenv("POSTGRES_USER", "snipebot")
POSTGRES_PASS  = os.getenv("POSTGRES_PASS", "snipebot")

# ── Telegram ────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT  = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Detection Thresholds ────────────────────────────────────
WHALE_THRESHOLD          = float(os.getenv("WHALE_THRESHOLD", 5000))
INSIDER_VOLUME_MULT      = float(os.getenv("INSIDER_VOLUME_MULT", 1.5))
INSIDER_TRADE_WINDOW     = int(os.getenv("INSIDER_TRADE_WINDOW", 20))
SPOOF_VANISH_SECONDS     = float(os.getenv("SPOOF_VANISH_SECONDS", 3.0))

# ── Signal Engine ───────────────────────────────────────────
SIGNAL_BUY_THRESHOLD     = float(os.getenv("SIGNAL_BUY_THRESHOLD", 0.30))
SIGNAL_SELL_THRESHOLD    = float(os.getenv("SIGNAL_SELL_THRESHOLD", -0.30))
CONFIDENCE_MIN           = float(os.getenv("CONFIDENCE_MIN", 0.35))
MIN_SIGNALS_REQUIRED     = int(os.getenv("MIN_SIGNALS_REQUIRED", 2))  # at least 2 detectors must agree

# Signal weights (must sum to 1.0)
W_WHALE                  = float(os.getenv("W_WHALE", 0.30))
W_INSIDER                = float(os.getenv("W_INSIDER", 0.25))
W_CLUSTER                = float(os.getenv("W_CLUSTER", 0.10))
W_FLOW                   = float(os.getenv("W_FLOW", 0.10))
W_CRYPTO                 = float(os.getenv("W_CRYPTO", 0.25))

# ── Execution ───────────────────────────────────────────────
TAKE_PROFIT              = float(os.getenv("TAKE_PROFIT", 0.05))
STOP_LOSS                = float(os.getenv("STOP_LOSS", 0.035))
TIME_EXIT_SECONDS        = int(os.getenv("TIME_EXIT_SECONDS", 600))
COOLDOWN_SECONDS         = int(os.getenv("COOLDOWN_SECONDS", 15))
MIN_HOLD_SECONDS         = int(os.getenv("MIN_HOLD_SECONDS", 15))
POSITION_SIZE_PCT        = float(os.getenv("POSITION_SIZE_PCT", 0.02))
STARTING_BANKROLL        = float(os.getenv("STARTING_BANKROLL", 10000))
MAX_OPEN_POSITIONS       = int(os.getenv("MAX_OPEN_POSITIONS", 5))
MOMENTUM_ENTRY_MAX       = float(os.getenv("MOMENTUM_ENTRY_MAX", 0.02))
SPOOF_BLOCK_PENALTY      = float(os.getenv("SPOOF_BLOCK_PENALTY", 0.5))  # block trade if spoof > this

# ── Crypto Context ──────────────────────────────────────────
CRYPTO_WINDOW_SECONDS    = int(os.getenv("CRYPTO_WINDOW_SECONDS", 300))
CRYPTO_SKIP_THRESHOLD    = float(os.getenv("CRYPTO_SKIP_THRESHOLD", 0.005))
VOLATILITY_MIN           = float(os.getenv("VOLATILITY_MIN", 0.001))

# ── Market Selection ────────────────────────────────────────
TOP_MARKETS_COUNT        = int(os.getenv("TOP_MARKETS_COUNT", 150))
CYCLE_INTERVAL           = float(os.getenv("CYCLE_INTERVAL", 0.5))
EXIT_CHECK_INTERVAL      = float(os.getenv("EXIT_CHECK_INTERVAL", 0.5))

# ── Market Type Awareness ───────────────────────────────────
# Keywords to classify markets — crypto markets use crypto signals heavily,
# sports markets rely on flow/whales and ignore crypto context
CRYPTO_KEYWORDS = ["bitcoin", "btc", "ethereum", "eth", "solana", "sol",
                   "crypto", "token", "defi", "nft", "blockchain", "coin"]
SPORTS_KEYWORDS = ["win", "beat", "score", "game", "match", "playoff",
                   "championship", "tournament", "vs", "fc", "nba", "nfl",
                   "mlb", "nhl", "premier league", "esports", "lol"]
