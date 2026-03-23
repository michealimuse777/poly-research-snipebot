"""Quick trade analysis."""
import csv
from collections import defaultdict

rows = list(csv.DictReader(open("trade_log.csv")))
print(f"{'='*60}")
print(f"  TRADE LOG ANALYSIS — {len(rows)} trades")
print(f"{'='*60}\n")

for i, r in enumerate(rows):
    pnl = float(r["pnl"])
    emoji = "WIN " if pnl > 0 else "LOSS"
    print(f"  {i+1:2}. [{emoji}] {r['timestamp'][-8:]} | {r['market'][:42]}")
    print(f"      {r['side']} | entry={r['entry_price']} exit={r['exit_price']} | PnL=${pnl:+.2f} ({float(r['pnl_pct']):+.1f}%)")
    print(f"      {r['exit_reason']} | hold={r['hold_time_s']}s | {r['signal_combo']} | score={r['signal_score']}")
    print()

wins = [r for r in rows if float(r["pnl"]) > 0]
losses = [r for r in rows if float(r["pnl"]) <= 0]
total_pnl = sum(float(r["pnl"]) for r in rows)

print(f"{'='*60}")
print(f"  SUMMARY")
print(f"{'='*60}")
print(f"  Record: {len(wins)}W / {len(losses)}L")
print(f"  Win Rate: {len(wins)/len(rows)*100:.0f}%")
print(f"  Total PnL: ${total_pnl:+.2f}")
print(f"  Avg Win:  ${sum(float(r['pnl']) for r in wins)/max(len(wins),1):+.2f}")
print(f"  Avg Loss: ${sum(float(r['pnl']) for r in losses)/max(len(losses),1):+.2f}")

print(f"\n{'='*60}")
print(f"  BY SIGNAL COMBO")
print(f"{'='*60}")
combo_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0})
for r in rows:
    pnl = float(r["pnl"])
    combo = r.get("signal_combo", "?")
    combo_stats[combo]["pnl"] += pnl
    if pnl > 0: combo_stats[combo]["wins"] += 1
    else: combo_stats[combo]["losses"] += 1

for combo, s in sorted(combo_stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
    total = s["wins"] + s["losses"]
    wr = f"{s['wins']/total*100:.0f}%" if total else "N/A"
    print(f"  {combo:30s} → ${s['pnl']:+8.2f} | {s['wins']}W/{s['losses']}L ({wr})")

print(f"\n{'='*60}")
print(f"  BY MARKET TYPE")
print(f"{'='*60}")
type_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0})
for r in rows:
    pnl = float(r["pnl"])
    mtype = r.get("market_type", "?")
    type_stats[mtype]["pnl"] += pnl
    if pnl > 0: type_stats[mtype]["wins"] += 1
    else: type_stats[mtype]["losses"] += 1

for mtype, s in sorted(type_stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
    total = s["wins"] + s["losses"]
    wr = f"{s['wins']/total*100:.0f}%" if total else "N/A"
    print(f"  {mtype:30s} → ${s['pnl']:+8.2f} | {s['wins']}W/{s['losses']}L ({wr})")

print(f"\n{'='*60}")
print(f"  BY EXIT REASON")
print(f"{'='*60}")
exit_stats = defaultdict(lambda: {"count": 0, "pnl": 0.0})
for r in rows:
    pnl = float(r["pnl"])
    reason = r.get("exit_reason", "?")
    exit_stats[reason]["count"] += 1
    exit_stats[reason]["pnl"] += pnl

for reason, s in sorted(exit_stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
    print(f"  {reason:30s} → ${s['pnl']:+8.2f} | {s['count']} trades")
