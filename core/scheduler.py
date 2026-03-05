"""
APScheduler polling loop for the Macro Trader bot.

Wires the full pipeline together:
  NewsClient → SentimentAnalyzer → SignalGenerator → RiskManager → BrokerClient → Database

Every poll interval:
  1. Fetch latest general news from Finnhub
  2. Skip articles already in the DB (dedup by article_id)
  3. Score new articles with FinBERT
  4. Run the rules engine to generate signals
  5. Persist signals; for each one run risk checks and execute via Alpaca
  6. Send Telegram alert on successful execution
"""

import logging
import signal as _signal
import threading
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from config import settings
from core.alerts import send_signal_alert
from core.broker import BrokerClient
from core.db import Database
from core.news import NewsClient
from core.risk_manager import RiskManager
from core.sentiment import SentimentAnalyzer
from core.signal_gen import SignalGenerator

logger = logging.getLogger(__name__)


class BotScheduler:
    """Owns the APScheduler instance and the shared pipeline components."""

    def __init__(self) -> None:
        logger.info("Initialising pipeline components …")
        self._db = Database()
        self._news = NewsClient()
        self._sentiment = SentimentAnalyzer()
        self._signals = SignalGenerator()
        self._broker = BrokerClient()
        self._risk = RiskManager(self._broker, self._db)
        self._scheduler = BackgroundScheduler(daemon=True)
        self._stop_event = threading.Event()
        logger.info("Pipeline ready.")

    # ------------------------------------------------------------------
    # Core poll job
    # ------------------------------------------------------------------

    def _poll(self) -> None:
        """Single poll cycle — called by APScheduler on the interval."""
        logger.info("Poll cycle starting …")

        try:
            raw_articles = self._news.get_general_news()
        except Exception:
            logger.exception("News fetch failed — skipping this cycle")
            return

        if not raw_articles:
            logger.info("No articles returned this cycle.")
            return

        # Dedup: only process articles we haven't seen before
        new_articles = [
            a for a in raw_articles
            if not self._db.article_exists(a.get("id", -1))
        ]
        logger.info(
            "Fetched %d articles, %d new (skipping %d duplicates)",
            len(raw_articles), len(new_articles), len(raw_articles) - len(new_articles),
        )

        if not new_articles:
            return

        # Score with FinBERT
        scored = self._sentiment.score_articles(new_articles)

        # Generate signals
        signals = self._signals.generate_signals(scored)

        # Persist articles
        saved_articles = 0
        for article in scored:
            rowid = self._db.save_article(article)
            if rowid:
                saved_articles += 1

        # Persist signals, run risk checks, execute approved orders
        saved_signals = 0
        executed_signals = 0
        for sig in signals:
            rowid = self._db.save_signal(sig)
            if not rowid:
                continue
            saved_signals += 1

            approved, reason = self._risk.can_trade()
            if not approved:
                logger.info("Signal skipped — risk check: %s", reason)
                self._db.update_signal_status(rowid, "skipped")
                continue

            qty = self._risk.position_qty(sig["ticker"])
            if qty <= 0:
                logger.info("Signal skipped — could not size position for %s", sig["ticker"])
                self._db.update_signal_status(rowid, "skipped")
                continue

            # Don't short-sell: skip sell signals if we have no position
            if sig["action"] == "sell":
                position = self._broker.get_position(sig["ticker"])
                if not position:
                    logger.info(
                        "Signal skipped — no position to sell for %s", sig["ticker"]
                    )
                    self._db.update_signal_status(rowid, "skipped")
                    continue

            order = self._broker.submit_market_order(sig["ticker"], qty, sig["action"])
            if order:
                executed_at = datetime.now(timezone.utc).isoformat()
                self._db.update_signal_status(rowid, "executed", executed_at)
                executed_signals += 1
                send_signal_alert({**sig, "qty": qty, "order_id": order.get("id")})
            else:
                self._db.update_signal_status(rowid, "skipped")

        logger.info(
            "Poll complete: saved %d articles, %d signals, %d executed",
            saved_articles, saved_signals, executed_signals,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the scheduler and block until a shutdown signal is received."""
        interval = settings.NEWS_POLL_INTERVAL_SECONDS

        self._scheduler.add_job(
            self._poll,
            trigger="interval",
            seconds=interval,
            id="news_poll",
            max_instances=1,       # never overlap if a poll runs slow
            coalesce=True,         # skip missed runs rather than piling up
        )

        # Register OS signal handlers so Ctrl-C / SIGTERM cleanly stop the bot
        _signal.signal(_signal.SIGINT, self._handle_shutdown)
        _signal.signal(_signal.SIGTERM, self._handle_shutdown)

        self._scheduler.start()
        logger.info(
            "Scheduler started — polling every %d s. Press Ctrl-C to stop.", interval
        )

        # Run one cycle immediately so we don't wait a full interval on startup
        self._poll()

        # Block the main thread until shutdown is requested
        self._stop_event.wait()

    def stop(self) -> None:
        """Gracefully stop the scheduler and close the DB connection."""
        logger.info("Shutting down …")
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        self._db.close()
        self._stop_event.set()
        logger.info("Shutdown complete.")

    def _handle_shutdown(self, signum, frame) -> None:  # noqa: ANN001
        logger.info("Received signal %d — stopping.", signum)
        self.stop()
