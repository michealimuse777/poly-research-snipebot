# 🐋 Polymarket Whale + Insider Snipe Bot

A real-time, multi-signal trading bot for [Polymarket](https://polymarket.com) prediction markets. Detects whale activity, insider flow, coordinated clusters, and spoofing — then executes selective, risk-controlled paper trades.

## Architecture

```
Polymarket WS ──► OrderbookCache ──► Synthetic Trade Detection
                       │                        │
                       ▼                        ▼
              WhaleDetector             TradeFeed
              SpoofingDetector          InsiderDetector
                       │                ClusterDetector
                       ▼                        │
                  SignalEngine ◄────────────────┘
                  (market-type aware)
                       │
                       ▼
                 SnipeExecutor
                 (cooldown + momentum filter)
                       │
                       ▼
               PositionManager ──► ExitEngine (TP/SL/Time)
                       │
                       ▼
                  trade_log.csv
```

## Detectors

| Detector | What it does |
|---|---|
| **Whale** | Detects large orders ($5K+) stacked on bid/ask side |
| **Insider** | Finds abnormal trade patterns — volume spikes, directional concentration |
| **Cluster** | Identifies coordinated multi-wallet trading within 30s windows |
| **Spoofing** | Catches fake orders that vanish in <3s — **blocks** trades when active |
| **Crypto Context** | BTC/ETH/SOL sentiment via CoinGecko (used for crypto markets only) |

## Risk Management

- **Max 3 positions** — no overtrading
- **Multi-signal requirement** — at least 2 detectors must agree in direction
- **Spoofing blocker** — active spoofing blocks all entries on that token
- **90s cooldown** per token between trades
- **30s minimum hold** — lets signals play out before TP/SL triggers
- **2.5:1 RR ratio** — TP=5%, SL=2%
- **Market-type awareness** — sports markets ignore crypto context, crypto markets weight it 45%
- **Validated synthetic trades** — only counts orderbook fills with $50+ notional AND price movement confirmation

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run in paper trading mode (no real money)
python main.py --paper --no-telegram

# With Telegram alerts
python main.py --paper
```

## Configuration

All settings in `settings.py` with env var overrides:

| Setting | Default | Description |
|---|---|---|
| `MAX_OPEN_POSITIONS` | 3 | Maximum concurrent positions |
| `TAKE_PROFIT` | 0.05 | 5% take profit |
| `STOP_LOSS` | 0.02 | 2% stop loss |
| `COOLDOWN_SECONDS` | 90 | Per-token cooldown |
| `MIN_HOLD_SECONDS` | 30 | Minimum hold before exit |
| `CONFIDENCE_MIN` | 0.35 | Minimum confidence to trade |
| `MIN_SIGNALS_REQUIRED` | 2 | Detectors that must agree |
| `WHALE_THRESHOLD` | 5000 | Dollar threshold for whale detection |

## Trade Logging

Every closed trade is logged to `trade_log.csv` with:
```
timestamp, market, market_type, side, entry_price, exit_price,
pnl, pnl_pct, hold_time_s, exit_reason, size, signal_combo, signal_score
```

Use this for edge discovery — analyze which signal combos (`whale+insider`, `whale+insider+cluster`) produce consistent profits.

## Requirements

- Python 3.10+
- Redis (for orderbook cache, falls back to in-memory)
- Dependencies: `websockets`, `aiohttp`, `redis`, `python-dotenv`

## Status

**Paper trading phase** — collecting data for edge discovery. Not yet proven profitable at scale.

## Disclaimer

This bot is for research and educational purposes. Prediction market trading carries risk. Always use paper mode first.
