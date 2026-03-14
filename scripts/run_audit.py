"""
Run the FIONA audit engine against the live SQLite DB and print a report.

Usage (on Fly.io):
    flyctl ssh console -a trading-bot-lingering-lake-4314 --command "python /app/scripts/run_audit.py"
    flyctl ssh console -a trading-bot-lingering-lake-4314 --command "python /app/scripts/run_audit.py --hours 48"
"""

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is on the path when run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.auditor import compute_metrics
from core.db import Database


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def print_report(m: dict) -> None:
    print(f"\n{'='*60}")
    print(f"  FIONA Audit Report — last {m['period_hours']}h")
    print(f"  Generated: {m['generated_at']}")
    print(f"{'='*60}\n")

    # --- Signals ---
    s = m["signals"]
    print("SIGNALS")
    print(f"  Total       : {s['total']}")
    print(f"  Executed    : {s['executed']}")
    print(f"  Skipped     : {s['skipped']}  ({_fmt_pct(s['skip_rate'])})")
    print(f"  Expired     : {s['expired']}  ({_fmt_pct(s['expiry_rate'])})")

    # --- Pipeline ---
    p = m["pipeline"]
    print("\nPIPELINE")
    print(f"  Articles ingested : {p['total_articles']}")
    print(f"  Articles/signal   : {p['articles_per_signal']}")
    if p["by_source"]:
        print("  By source:")
        for src, count in sorted(p["by_source"].items(), key=lambda x: -x[1]):
            print(f"    {src:<30} {count}")

    # --- Themes ---
    if m["themes"]:
        print("\nTHEMES")
        for theme, data in sorted(m["themes"].items(), key=lambda x: -x[1]["total"]):
            print(
                f"  {theme:<25} total={data['total']}  exec={data['executed']}"
                f"  skip={data['skipped']} ({_fmt_pct(data['skip_rate'])})"
                f"  conf={data['avg_confidence']:.2f}"
            )
            if data["skip_reasons"]:
                for reason, count in data["skip_reasons"].items():
                    print(f"    skip_reason: {reason} x{count}")

    # --- P&L ---
    if m["pnl_by_theme"]:
        print("\nP&L BY THEME")
        for theme, data in m["pnl_by_theme"].items():
            print(
                f"  {theme:<25} trades={data['count']}"
                f"  win_rate={_fmt_pct(data['win_rate'])}"
                f"  avg_return={data['avg_return_pct']:+.2f}%"
            )
    else:
        print("\nP&L BY THEME\n  No closed trades with fill+exit prices recorded.")

    # --- Anomalies ---
    print("\nANOMALIES")
    if m["anomalies"]:
        for a in m["anomalies"]:
            print(f"  !! {a}")
    else:
        print("  None")

    print(f"\n{'='*60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="FIONA audit report")
    parser.add_argument("--hours", type=int, default=24, help="Lookback window in hours (default: 24)")
    parser.add_argument("--json", action="store_true", help="Dump raw JSON instead of formatted report")
    args = parser.parse_args()

    db = Database()
    metrics = compute_metrics(db, hours=args.hours)

    if args.json:
        print(json.dumps(metrics, indent=2))
    else:
        print_report(metrics)


if __name__ == "__main__":
    main()
