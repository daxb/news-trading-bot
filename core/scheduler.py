"""
APScheduler polling loop for FIONA (Fast Inference On News Alpha).

Wires the full pipeline together:
  NewsClient + RSSClient → SentimentAnalyzer → SignalGenerator → RiskManager → BrokerClient → Database

Every poll interval:
  1. Fetch latest news from Finnhub + all RSS feeds
  2. Skip articles already in the DB (dedup by article_id)
  3. Score new articles with FinBERT
  4. Run the rules engine to generate signals
  5. Persist signals; for each one run risk checks and execute via Alpaca
  6. Send Telegram alert on successful execution
"""

import logging
import signal as _signal
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler

from config import settings
from core.alerts import send_hourly_update, send_shutdown_alert, send_signal_alert, send_startup_alert
from core.broker import BrokerClient
from core.db import Database
from core.dedup import deduplicate
from core.exit_manager import ExitManager
from core.forex import ForexBroker
from core.macro import MacroClient
from core.macro_context import MacroContext
from core.news import NewsClient
from core.risk_manager import RiskManager
from core.rss import RSSClient
from core.sentiment import SentimentAnalyzer
from core.signal_gen import SignalGenerator

logger = logging.getLogger(__name__)


class BotScheduler:
    """Owns the APScheduler instance and the shared pipeline components."""

    def __init__(self) -> None:
        logger.info("Initialising pipeline components …")
        self._db = Database()
        self._news = NewsClient()
        self._rss = RSSClient()
        self._sentiment = SentimentAnalyzer()
        self._signals = SignalGenerator()
        self._broker = BrokerClient()
        self._risk = RiskManager(self._broker, self._db)

        # OANDA — optional; gracefully disabled if keys are absent
        self._forex: ForexBroker | None = None
        self._forex_risk: RiskManager | None = None
        if settings.OANDA_API_KEY and settings.OANDA_ACCOUNT_ID:
            self._forex = ForexBroker()
            self._forex_risk = RiskManager(self._forex, self._db)
        else:
            logger.info("OANDA not configured — forex signals will be skipped")

        self._macro_ctx = MacroContext(MacroClient())
        self._exit_mgr = ExitManager(self._broker, self._db, forex=self._forex)
        self._scheduler = BackgroundScheduler(daemon=True)
        self._stop_event = threading.Event()
        logger.info("Pipeline ready.")

    # ------------------------------------------------------------------
    # Core poll job
    # ------------------------------------------------------------------

    def _poll(self) -> None:
        """Single poll cycle — called by APScheduler on the interval."""
        logger.info("Poll cycle starting …")

        # Fetch from all sources concurrently
        raw_articles: list[dict] = []
        sources = {
            "finnhub": self._news.get_general_news,
            "rss":     self._rss.get_articles,
        }
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_to_name = {
                executor.submit(fn): name
                for name, fn in sources.items()
            }
            for future in as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    raw_articles.extend(future.result())
                except Exception:
                    logger.exception("%s fetch failed — skipping", name)

        if not raw_articles:
            logger.info("No articles returned this cycle.")
            return

        # Dedup by article_id against the DB, then by ID within this batch
        seen_ids: set[int] = set()
        new_articles: list[dict] = []
        for a in raw_articles:
            aid = a.get("id", -1)
            if aid in seen_ids:
                continue
            seen_ids.add(aid)
            if not self._db.article_exists(aid):
                new_articles.append(a)

        logger.info(
            "Fetched %d articles total, %d new after ID-dedup (skipping %d)",
            len(raw_articles), len(new_articles), len(raw_articles) - len(new_articles),
        )

        if not new_articles:
            return

        # Similarity dedup — drop cross-source near-duplicates
        recent_headlines = self._db.get_recent_headlines(hours=settings.DEDUP_WINDOW_HOURS)
        new_articles = deduplicate(new_articles, recent_headlines)

        if not new_articles:
            logger.info("All articles were near-duplicates — nothing to process.")
            return

        # Pre-filter: drop articles that can't match any trading rule keyword.
        # This avoids running FinBERT on content like dividend history listicles.
        relevant_articles = [a for a in new_articles if self._signals.is_relevant(a)]
        dropped = len(new_articles) - len(relevant_articles)
        if dropped:
            logger.info(
                "Pre-filter: dropped %d irrelevant articles, %d remain for scoring",
                dropped, len(relevant_articles),
            )
        new_articles = relevant_articles

        if not new_articles:
            logger.info("No relevant articles after pre-filter — nothing to process.")
            return

        # Cap articles per cycle so FinBERT scoring stays well under the poll interval.
        # 250 articles × ~2 s/article on CPU = 8+ min, blocking subsequent cycles.
        # 50 articles × ~2 s = ~100 s — leaves plenty of headroom.
        max_per_cycle = settings.MAX_ARTICLES_PER_CYCLE
        if len(new_articles) > max_per_cycle:
            logger.info(
                "Capping batch: %d → %d articles (MAX_ARTICLES_PER_CYCLE=%d)",
                len(new_articles), max_per_cycle, max_per_cycle,
            )
            new_articles = new_articles[:max_per_cycle]

        # Tick macro context — refreshes FRED data every N cycles
        self._macro_ctx.tick()

        # Score with FinBERT
        scored = self._sentiment.score_articles(new_articles)

        # Generate signals, then filter/adjust by macro context
        signals = self._signals.generate_signals(scored)
        signals = self._macro_ctx.adjust_signals(signals)

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

            # Route to the correct broker based on instrument format
            is_forex = "_" in sig["ticker"]
            if is_forex:
                if not self._forex or not self._forex_risk:
                    logger.info(
                        "Signal skipped — OANDA not configured for %s", sig["ticker"]
                    )
                    self._db.update_signal_status(rowid, "skipped")
                    continue
                risk   = self._forex_risk
                broker = self._forex
            else:
                risk   = self._risk
                broker = self._broker

            approved, reason = risk.can_trade()
            if not approved:
                logger.info("Signal skipped — risk check: %s", reason)
                self._db.update_signal_status(rowid, "skipped")
                continue

            qty = risk.position_qty(sig["ticker"])
            if qty <= 0:
                logger.info("Signal skipped — could not size position for %s", sig["ticker"])
                self._db.update_signal_status(rowid, "skipped")
                continue

            # Equity only: don't short-sell if we have no position
            # Forex allows shorting natively so this check is skipped
            if not is_forex and sig["action"] == "sell":
                position = broker.get_position(sig["ticker"])
                if not position:
                    logger.info(
                        "Signal skipped — no position to sell for %s", sig["ticker"]
                    )
                    self._db.update_signal_status(rowid, "skipped")
                    continue

            order = broker.submit_market_order(sig["ticker"], qty, sig["action"])
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
    # Hourly digest
    # ------------------------------------------------------------------

    _ET = ZoneInfo("America/New_York")
    # Market open/close in ET (inclusive on open, exclusive on close)
    _MARKET_OPEN_H = 9
    _MARKET_OPEN_M = 30
    _MARKET_CLOSE_H = 16

    def _is_trading_hours(self) -> bool:
        """Return True if current ET time is within regular US market hours."""
        now = datetime.now(self._ET)
        if now.weekday() >= 5:          # Saturday=5, Sunday=6
            return False
        open_mins = self._MARKET_OPEN_H * 60 + self._MARKET_OPEN_M
        close_mins = self._MARKET_CLOSE_H * 60
        current_mins = now.hour * 60 + now.minute
        return open_mins <= current_mins < close_mins

    def _hourly_update(self) -> None:
        """Send a Telegram digest of signals, trades, and P&L. No-ops outside trading hours."""
        if not self._is_trading_hours():
            logger.debug("Hourly update skipped — outside trading hours")
            return

        logger.info("Sending hourly Telegram update …")
        try:
            signals = self._db.get_signals_since(hours=1)
            account = self._broker.get_account()
            positions = self._broker.get_positions()
            open_orders = self._broker.get_orders(status="open")
            send_hourly_update(signals, account, positions, open_orders)
        except Exception:
            logger.exception("Failed to build/send hourly update")

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
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.add_job(
            self._exit_mgr.check_exits,
            trigger="interval",
            seconds=settings.POSITION_MONITOR_INTERVAL_SECONDS,
            id="position_monitor",
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.add_job(
            self._hourly_update,
            trigger="cron",
            minute=0,
            id="hourly_update",
            max_instances=1,
            coalesce=True,
        )

        # Register OS signal handlers so Ctrl-C / SIGTERM cleanly stop the bot
        _signal.signal(_signal.SIGINT, self._handle_shutdown)
        _signal.signal(_signal.SIGTERM, self._handle_shutdown)

        self._scheduler.start()
        logger.info(
            "Scheduler started — polling every %d s. Press Ctrl-C to stop.", interval
        )
        send_startup_alert()

        # Run one cycle immediately so we don't wait a full interval on startup
        self._poll()
        # Send an hourly update immediately on startup (if within trading hours)
        self._hourly_update()

        # Block the main thread until shutdown is requested
        self._stop_event.wait()

    def stop(self) -> None:
        """Gracefully stop the scheduler and close the DB connection."""
        logger.info("Shutting down …")
        send_shutdown_alert()
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        self._db.close()
        self._stop_event.set()
        logger.info("Shutdown complete.")

    def _handle_shutdown(self, signum, frame) -> None:  # noqa: ANN001
        logger.info("Received signal %d — stopping.", signum)
        self.stop()
