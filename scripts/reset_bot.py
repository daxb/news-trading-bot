#!/usr/bin/env python3
"""
Reset the bot to a clean state for paper trading.

What this script does automatically (via API):
  1. Cancel all open Alpaca orders
  2. Close all open Alpaca positions
  3. Close all open OANDA positions (if configured)
  4. Clear the local SQLite database (articles, signals, bot_state)

What requires manual action on each broker's web dashboard:
  • Alpaca paper balance reset → https://app.alpaca.markets/paper-trading/overview
      Account → "Reset Paper Account" (restores to $100,000)
  • OANDA practice balance reset → https://www.oanda.com/demo-account/
      My Account → Manage Funds → Reset Account

Usage:
    python scripts/reset_bot.py           # prompts for confirmation
    python scripts/reset_bot.py --yes     # skip confirmation prompt
    python scripts/reset_bot.py --db-only # only clear the database, skip brokers
"""

import argparse
import logging
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Alpaca
# ------------------------------------------------------------------

def cancel_alpaca_orders() -> int:
    """Cancel all open Alpaca orders. Returns number cancelled."""
    from alpaca.trading.client import TradingClient

    client = TradingClient(
        api_key=settings.ALPACA_API_KEY,
        secret_key=settings.ALPACA_SECRET_KEY,
        paper=settings.PAPER_TRADING,
    )
    try:
        responses = client.cancel_orders()
        count = len(responses) if responses else 0
        logger.info("Cancelled %d open Alpaca order(s)", count)
        return count
    except Exception:
        logger.exception("Failed to cancel Alpaca orders")
        return 0


def close_alpaca_positions() -> int:
    """Close all open Alpaca positions. Returns number closed."""
    from core.broker import BrokerClient

    broker = BrokerClient()
    positions = broker.get_positions()
    if not positions:
        logger.info("No open Alpaca positions")
        return 0

    closed = 0
    for pos in positions:
        symbol = pos["symbol"]
        result = broker.close_position(symbol)
        if result:
            closed += 1
            logger.info("  Closed %s (qty=%.4f, side=%s)", symbol, pos["qty"], pos["side"])
        else:
            logger.warning("  Failed to close %s", symbol)
    return closed


# ------------------------------------------------------------------
# OANDA
# ------------------------------------------------------------------

def close_oanda_positions() -> int:
    """Close all open OANDA positions. Skips gracefully if not configured."""
    if not settings.OANDA_API_KEY or not settings.OANDA_ACCOUNT_ID:
        logger.info("OANDA not configured — skipping")
        return 0

    try:
        from core.forex import ForexBroker

        fx = ForexBroker()
        positions = fx.get_positions()
        if not positions:
            logger.info("No open OANDA positions")
            return 0

        closed = 0
        for pos in positions:
            instrument = pos["instrument"]
            result = fx.close_position(instrument)
            if result:
                closed += 1
                logger.info(
                    "  Closed %s (units=%d, side=%s)",
                    instrument, pos["units"], pos["side"],
                )
            else:
                logger.warning("  Failed to close %s", instrument)
        return closed
    except Exception:
        logger.exception("Failed to close OANDA positions")
        return 0


# ------------------------------------------------------------------
# Database
# ------------------------------------------------------------------

def clear_database() -> None:
    """Delete all rows from articles, signals, and bot_state, and reset auto-increment."""
    db_path = settings.DB_PATH

    if not os.path.exists(db_path):
        logger.info("No database found at %s — nothing to clear", db_path)
        return

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DELETE FROM articles")
        conn.execute("DELETE FROM signals")
        conn.execute("DELETE FROM bot_state")
        # Reset auto-increment counters so IDs start from 1 again.
        conn.execute(
            "DELETE FROM sqlite_sequence WHERE name IN ('articles', 'signals')"
        )
        conn.commit()
        logger.info(
            "Cleared database: articles, signals, bot_state tables at %s", db_path
        )
    except Exception:
        logger.exception("Failed to clear database")
    finally:
        conn.close()


# ------------------------------------------------------------------
# Manual steps reminder
# ------------------------------------------------------------------

def _print_manual_steps() -> None:
    """Print the steps that require action on each broker's web dashboard."""
    has_alpaca = bool(settings.ALPACA_API_KEY)
    has_oanda = bool(settings.OANDA_API_KEY)

    if not (has_alpaca or has_oanda):
        return

    print("To restore the paper account balance(s) to their starting value,")
    print("complete the following steps manually:\n")

    if has_alpaca:
        print("  Alpaca paper balance reset")
        print("    1. Go to https://app.alpaca.markets/paper-trading/overview")
        print("    2. Click 'Reset Paper Account' (restores the $100,000 balance)")
        print()

    if has_oanda:
        print("  OANDA practice balance reset")
        print("    1. Log in at https://www.oanda.com")
        print("    2. Navigate to My Account → Manage Funds → Reset Account")
        print()

    print("Then restart the bot: python scripts/run_bot.py")
    print()


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reset FIONA to a clean state for paper trading."
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip the confirmation prompt",
    )
    parser.add_argument(
        "--db-only",
        action="store_true",
        help="Only clear the database; skip broker order/position resets",
    )
    args = parser.parse_args()

    mode = "paper" if settings.PAPER_TRADING else "LIVE"
    print(f"\n=== FIONA Bot Reset ({mode} mode) ===\n")
    print("Automated steps (via API):")
    if not args.db_only:
        print("  • Cancel all open Alpaca orders")
        print("  • Close all open Alpaca positions")
        if settings.OANDA_API_KEY:
            print("  • Close all open OANDA positions")
    print("  • Clear the SQLite database (articles, signals, bot_state)")
    print()
    print("Manual step required afterward (web dashboard):")
    print("  • Reset paper account balance(s) back to starting value")
    print()

    if not args.yes:
        try:
            answer = input("Proceed? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(0)
        if answer not in ("y", "yes"):
            print("Aborted.")
            sys.exit(0)

    print()

    if not args.db_only:
        logger.info("=== Alpaca ===")
        if not settings.ALPACA_API_KEY or not settings.ALPACA_SECRET_KEY:
            logger.warning("ALPACA_API_KEY / ALPACA_SECRET_KEY not set — skipping")
        else:
            cancel_alpaca_orders()
            close_alpaca_positions()

        logger.info("=== OANDA ===")
        close_oanda_positions()

    logger.info("=== Database ===")
    clear_database()

    print("\nAutomated reset complete.")
    print()
    _print_manual_steps()


if __name__ == "__main__":
    main()
