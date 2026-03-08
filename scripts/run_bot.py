"""
Entry point for the Macro Trader bot.

Usage (from project root with venv active):
    python scripts/run_bot.py

Environment:
    All configuration is read from .env via config/settings.py.
    At minimum, set FINNHUB_API_KEY, FRED_API_KEY, ALPACA_API_KEY,
    and ALPACA_SECRET_KEY.

    Optional overrides:
        NEWS_POLL_INTERVAL_SECONDS=300   # how often to poll (default 5 min)
        SIGNAL_CONVICTION_THRESHOLD=0.4  # min confidence to record a signal
        DB_PATH=data/trading.db          # SQLite file location
"""

import logging
import sys
from pathlib import Path

# Ensure the project root is on sys.path when run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.scheduler import BotScheduler


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    # Suppress noisy third-party loggers
    for noisy in ("urllib3", "httpx", "httpcore", "transformers", "torch"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> None:
    _configure_logging()
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("  FIONA — starting up")
    logger.info("=" * 60)

    try:
        bot = BotScheduler()
    except Exception:
        logger.exception("Failed to initialize BotScheduler — check API keys and config")
        sys.exit(1)

    try:
        bot.start()  # blocks until Ctrl-C / SIGTERM
    except KeyboardInterrupt:
        logger.info("Shutting down (KeyboardInterrupt)")
    except Exception:
        logger.exception("Bot crashed unexpectedly")
        sys.exit(1)


if __name__ == "__main__":
    main()
