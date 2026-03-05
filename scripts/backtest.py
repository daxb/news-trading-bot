"""
Walk-forward backtest runner for the Macro Trader bot.

Usage (from project root, venv active):
    python scripts/backtest.py
    python scripts/backtest.py --hold-hours 2 --window-days 14
    python scripts/backtest.py --min-confidence 0.5
"""

import argparse
import logging
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.backtester import Backtester, TradeResult, WindowResult
from core.db import Database


def _pct(v: float) -> str:
    return f"{v * 100:+.2f}%"


def _bar(v: float, width: int = 20) -> str:
    """Simple ASCII bar representing a 0–100% win rate."""
    filled = round(v * width)
    return "█" * filled + "░" * (width - filled)


def print_section(title: str) -> None:
    print(f"\n── {title} {'─' * max(0, 50 - len(title))}")


def run(hold_hours: int, window_days: int, min_confidence: float) -> None:
    logging.basicConfig(level=logging.WARNING)  # suppress info logs during backtest

    db = Database()
    bt = Backtester(db, hold_hours=hold_hours, position_size=5000.0)

    print("\n╔══════════════════════════════════════════════════════╗")
    print("║        Walk-Forward Backtest — Macro Trader          ║")
    print("╚══════════════════════════════════════════════════════╝")
    print(f"  Hold period    : {hold_hours}h")
    print(f"  Window size    : {window_days} days")
    print(f"  Min confidence : {min_confidence:.2f}")
    print(f"  Position size  : $5,000 per trade")
    print("\n  Fetching price data from yfinance …")

    windows = bt.run(window_days=window_days, min_confidence=min_confidence)

    all_trades: list[TradeResult] = [t for w in windows for t in w.trades]
    total_signals = db.get_signals(limit=10_000)
    simulated = len(all_trades)
    skipped = len(total_signals) - simulated

    if not all_trades:
        print("\n  No completed trades to report.")
        print("  Tip: signals need at least hold_hours of history to have an exit price.")
        return

    # ── Overall ──────────────────────────────────────────────────────────────
    print_section("OVERALL")

    wins = sum(1 for t in all_trades if t.correct)
    win_rate = wins / simulated
    avg_ret = sum(t.pnl_pct for t in all_trades) / simulated
    best  = max(all_trades, key=lambda t: t.pnl_pct)
    worst = min(all_trades, key=lambda t: t.pnl_pct)

    # Compound total return
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for t in sorted(all_trades, key=lambda t: t.entry_time):
        equity *= (1 + t.pnl_pct)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)

    gross_profit = sum(t.pnl_pct for t in all_trades if t.pnl_pct > 0)
    gross_loss   = abs(sum(t.pnl_pct for t in all_trades if t.pnl_pct < 0))
    pf = gross_profit / gross_loss if gross_loss else float("inf")

    print(f"  Signals in DB  : {len(total_signals)}")
    print(f"  Simulated      : {simulated}  (skipped {skipped} — no exit data yet)")
    print(f"  Win rate       : {win_rate * 100:.1f}%  ({wins}/{simulated})  {_bar(win_rate)}")
    print(f"  Avg return     : {_pct(avg_ret)} per trade")
    print(f"  Total return   : {_pct(equity - 1.0)}")
    print(f"  Max drawdown   : {_pct(-max_dd)}")
    print(f"  Profit factor  : {pf:.2f}")
    print(f"  Best trade     : {_pct(best.pnl_pct)}  ({best.ticker} {best.action} — {best.theme})")
    print(f"  Worst trade    : {_pct(worst.pnl_pct)}  ({worst.ticker} {worst.action} — {worst.theme})")

    # ── By window ────────────────────────────────────────────────────────────
    print_section("BY WINDOW")
    print(f"  {'Window':<22}  {'Trades':>6}  {'Win%':>6}  {'Return':>8}  {'Max DD':>7}")
    print(f"  {'─'*22}  {'─'*6}  {'─'*6}  {'─'*8}  {'─'*7}")
    for w in windows:
        if not w.trades:
            continue
        label = f"{w.start.strftime('%Y-%m-%d')} → {w.end.strftime('%m-%d')}"
        print(
            f"  {label:<22}  {len(w.trades):>6}  "
            f"{w.win_rate * 100:>5.1f}%  "
            f"{_pct(w.total_return_pct):>8}  "
            f"{_pct(-w.max_drawdown_pct):>7}"
        )

    # ── By theme ─────────────────────────────────────────────────────────────
    print_section("BY THEME")
    theme_trades: dict[str, list[TradeResult]] = defaultdict(list)
    for t in all_trades:
        theme_trades[t.theme].append(t)

    print(f"  {'Theme':<24}  {'Trades':>6}  {'Win%':>6}  {'Avg Ret':>8}")
    print(f"  {'─'*24}  {'─'*6}  {'─'*6}  {'─'*8}")
    for theme, trades in sorted(theme_trades.items(), key=lambda x: -len(x[1])):
        wr = sum(1 for t in trades if t.correct) / len(trades)
        ar = sum(t.pnl_pct for t in trades) / len(trades)
        print(f"  {theme:<24}  {len(trades):>6}  {wr * 100:>5.1f}%  {_pct(ar):>8}")

    # ── By ticker ────────────────────────────────────────────────────────────
    print_section("BY TICKER")
    ticker_trades: dict[str, list[TradeResult]] = defaultdict(list)
    for t in all_trades:
        ticker_trades[t.ticker].append(t)

    print(f"  {'Ticker':<12}  {'Trades':>6}  {'Win%':>6}  {'Avg Ret':>8}")
    print(f"  {'─'*12}  {'─'*6}  {'─'*6}  {'─'*8}")
    for ticker, trades in sorted(ticker_trades.items(), key=lambda x: -len(x[1])):
        wr = sum(1 for t in trades if t.correct) / len(trades)
        ar = sum(t.pnl_pct for t in trades) / len(trades)
        print(f"  {ticker:<12}  {len(trades):>6}  {wr * 100:>5.1f}%  {_pct(ar):>8}")

    print("\n  Notes:")
    print("  - Signals generated outside US market hours (pre-market/after-hours)")
    print("    will show 0% return as yfinance returns the same off-hours price")
    print("    for both entry and exit. Results improve as the bot accumulates")
    print("    signals during live trading sessions.")
    print("  - Statistical significance requires weeks/months of signal history.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Walk-forward backtest for Macro Trader")
    parser.add_argument("--hold-hours",     type=int,   default=4,   help="Hours to hold each position (default: 4)")
    parser.add_argument("--window-days",    type=int,   default=7,   help="Walk-forward window size in days (default: 7)")
    parser.add_argument("--min-confidence", type=float, default=0.0, help="Minimum signal confidence to include (default: 0.0)")
    args = parser.parse_args()

    run(
        hold_hours=args.hold_hours,
        window_days=args.window_days,
        min_confidence=args.min_confidence,
    )
