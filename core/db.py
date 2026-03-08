"""
SQLite repository for the Macro Trader bot.

Stores scored articles and generated signals so the scheduler can:
  - skip articles already processed (dedup by article_id)
  - hand pending signals to the execution layer
  - retain history for backtesting and review

Schema
------
articles
    id              INTEGER PK AUTOINCREMENT
    article_id      INTEGER UNIQUE   -- Finnhub id; dedup key
    headline        TEXT
    summary         TEXT
    source          TEXT
    url             TEXT
    category        TEXT
    datetime        TEXT             -- UTC ISO-8601
    related         TEXT
    sentiment_label TEXT             -- positive | negative | neutral
    sentiment_score REAL             -- confidence [0.0, 1.0]
    fetched_at      TEXT             -- UTC ISO-8601, when we stored it

signals
    id              INTEGER PK AUTOINCREMENT
    article_id      INTEGER          -- FK → articles.article_id
    ticker          TEXT
    action          TEXT             -- buy | sell | hold
    confidence      REAL             -- [0.0, 1.0]
    theme           TEXT             -- e.g. "fed_hawkish", "geopolitical_risk"
    rationale       TEXT
    status          TEXT DEFAULT 'pending'   -- pending | executed | skipped | expired
    created_at      TEXT             -- UTC ISO-8601
    executed_at     TEXT             -- UTC ISO-8601, nullable
    fill_price      REAL             -- approximate fill price, nullable
    exit_price      REAL             -- exit price for P&L tracking, nullable
    source          TEXT             -- article source for multi-source corroboration
    skip_reason     TEXT             -- why the signal was skipped, nullable
"""

import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone

from config import settings

logger = logging.getLogger(__name__)

_CREATE_ARTICLES = """
CREATE TABLE IF NOT EXISTS articles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id      INTEGER UNIQUE,
    headline        TEXT,
    summary         TEXT,
    source          TEXT,
    url             TEXT,
    category        TEXT,
    datetime        TEXT,
    related         TEXT,
    sentiment_label TEXT,
    sentiment_score REAL,
    fetched_at      TEXT
);
"""

_CREATE_SIGNALS = """
CREATE TABLE IF NOT EXISTS signals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id  INTEGER,
    ticker      TEXT,
    action      TEXT,
    confidence  REAL,
    theme       TEXT,
    rationale   TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TEXT,
    executed_at TEXT,
    fill_price  REAL,
    exit_price  REAL
);
"""

_CREATE_BOT_STATE = """
CREATE TABLE IF NOT EXISTS bot_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

_VALID_SIGNAL_STATUSES = {"pending", "executed", "skipped", "expired"}


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """SQLite repository — one connection per instance."""

    def __init__(self, db_path: str | None = None) -> None:
        path = db_path or settings.DB_PATH
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # WAL mode allows concurrent readers (dashboard process) alongside the bot writer.
        self._conn.execute("PRAGMA journal_mode=WAL")
        # Serialize writes from concurrent scheduler threads (_poll + check_exits).
        self._write_lock = threading.Lock()
        self._init_schema()
        logger.info("Database ready at %s", path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(_CREATE_ARTICLES)
            self._conn.execute(_CREATE_SIGNALS)
            self._conn.execute(_CREATE_BOT_STATE)
            # Indexes for time-range queries used by dashboard and auditor
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_signals_created_at ON signals (created_at)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_articles_fetched_at ON articles (fetched_at)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_signals_status ON signals (status)"
            )
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        """Add columns introduced after the initial schema. Safe to run on existing DBs."""
        migrations = [
            ("signals", "fill_price",   "REAL"),
            ("signals", "exit_price",   "REAL"),
            ("signals", "source",       "TEXT"),   # article source for multi-source corroboration
            ("signals", "skip_reason",  "TEXT"),   # why the signal was skipped
        ]
        for table, col, coltype in migrations:
            try:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
                logger.info("Schema migration: added %s.%s", table, col)
            except sqlite3.OperationalError:
                pass  # column already exists

    # ------------------------------------------------------------------
    # Articles
    # ------------------------------------------------------------------

    def save_article(self, article: dict) -> int | None:
        """
        Persist a scored article. Silently skips duplicates (IGNORE).

        Args:
            article: dict from news.py + sentiment keys added by sentiment.py.

        Returns:
            The new rowid, or None if the article already existed / on error.
        """
        sql = """
            INSERT OR IGNORE INTO articles
                (article_id, headline, summary, source, url, category,
                 datetime, related, sentiment_label, sentiment_score, fetched_at)
            VALUES
                (:article_id, :headline, :summary, :source, :url, :category,
                 :datetime, :related, :sentiment_label, :sentiment_score, :fetched_at)
        """
        params = {
            "article_id": article.get("id"),
            "headline": article.get("headline", ""),
            "summary": article.get("summary", ""),
            "source": article.get("source", ""),
            "url": article.get("url", ""),
            "category": article.get("category", ""),
            "datetime": article.get("datetime"),
            "related": article.get("related", ""),
            "sentiment_label": article.get("sentiment_label"),
            "sentiment_score": article.get("sentiment_score"),
            "fetched_at": _now_utc(),
        }
        try:
            with self._write_lock, self._conn:
                cursor = self._conn.execute(sql, params)
                rowid = cursor.lastrowid if cursor.rowcount > 0 else None
                if rowid:
                    logger.debug("Saved article id=%s rowid=%d", params["article_id"], rowid)
                return rowid
        except sqlite3.OperationalError as e:
            logger.warning("DB operational error saving article id=%s: %s", params.get("article_id"), e)
            return None
        except Exception:
            logger.exception("Failed to save article id=%s", params.get("article_id"))
            return None

    def article_exists(self, article_id: int) -> bool:
        """Return True if an article with this Finnhub id is already stored."""
        try:
            row = self._conn.execute(
                "SELECT 1 FROM articles WHERE article_id = ?", (article_id,)
            ).fetchone()
            return row is not None
        except Exception:
            logger.exception("Failed to check article existence for id=%s", article_id)
            return False

    def get_recent_headlines(self, hours: int = 4) -> list[str]:
        """Return headlines stored in the last `hours` hours (UTC)."""
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        try:
            rows = self._conn.execute(
                "SELECT headline FROM articles WHERE fetched_at >= ? AND headline != ''",
                (cutoff,),
            ).fetchall()
            return [r["headline"] for r in rows]
        except Exception:
            logger.exception("Failed to fetch recent headlines")
            return []

    def get_articles(self, limit: int = 50, sentiment_label: str | None = None) -> list[dict]:
        """
        Fetch stored articles, newest first.

        Args:
            limit:           Max rows to return.
            sentiment_label: Optional filter ('positive', 'negative', 'neutral').
        """
        try:
            if sentiment_label:
                rows = self._conn.execute(
                    "SELECT * FROM articles WHERE sentiment_label = ? "
                    "ORDER BY id DESC LIMIT ?",
                    (sentiment_label, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM articles ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            logger.exception("Failed to fetch articles")
            return []

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def save_signal(self, signal: dict) -> int | None:
        """
        Persist a trading signal.

        Args:
            signal: dict with keys article_id, ticker, action, confidence,
                    theme, rationale. status defaults to 'pending'.

        Returns:
            The new rowid, or None on error.
        """
        sql = """
            INSERT INTO signals
                (article_id, ticker, action, confidence, theme, rationale,
                 status, created_at, executed_at, source, skip_reason)
            VALUES
                (:article_id, :ticker, :action, :confidence, :theme, :rationale,
                 :status, :created_at, :executed_at, :source, :skip_reason)
        """
        params = {
            "article_id": signal.get("article_id"),
            "ticker": signal.get("ticker", ""),
            "action": signal.get("action", ""),
            "confidence": signal.get("confidence", 0.0),
            "theme": signal.get("theme", ""),
            "rationale": signal.get("rationale", ""),
            "status": signal.get("status", "pending"),
            "created_at": signal.get("created_at", _now_utc()),
            "executed_at": signal.get("executed_at"),
            "source": signal.get("source", ""),
            "skip_reason": signal.get("skip_reason"),
        }
        try:
            with self._write_lock, self._conn:
                cursor = self._conn.execute(sql, params)
                logger.debug(
                    "Saved signal: %s %s (confidence=%.2f)",
                    params["action"], params["ticker"], params["confidence"],
                )
                return cursor.lastrowid
        except sqlite3.OperationalError as e:
            logger.warning("DB operational error saving signal for ticker=%s: %s", params.get("ticker"), e)
            return None
        except Exception:
            logger.exception(
                "Failed to save signal for ticker=%s", params.get("ticker")
            )
            return None

    def get_signals(self, limit: int = 100, status: str | None = None) -> list[dict]:
        """
        Fetch signals, newest first.

        Args:
            limit:  Max rows to return.
            status: Optional filter — 'pending', 'executed', 'skipped', 'expired'.
        """
        try:
            if status:
                rows = self._conn.execute(
                    "SELECT * FROM signals WHERE status = ? ORDER BY id DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            logger.exception("Failed to fetch signals")
            return []

    def get_signals_since(self, hours: int = 1) -> list[dict]:
        """Return all signals created in the last `hours` hours (UTC), newest first."""
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        try:
            rows = self._conn.execute(
                "SELECT * FROM signals WHERE created_at >= ? ORDER BY id DESC",
                (cutoff,),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            logger.exception("Failed to fetch signals since %d hours ago", hours)
            return []

    def get_pending_signals(self) -> list[dict]:
        """Return all signals with status='pending', oldest first."""
        try:
            rows = self._conn.execute(
                "SELECT * FROM signals WHERE status = 'pending' ORDER BY id ASC"
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            logger.exception("Failed to fetch pending signals")
            return []

    def update_signal_status(
        self,
        signal_id: int,
        status: str,
        executed_at: str | None = None,
        fill_price: float | None = None,
        skip_reason: str | None = None,
    ) -> bool:
        """
        Update a signal's status, and optionally its fill price or skip reason.

        Args:
            signal_id:   The signal's primary key.
            status:      One of pending | executed | skipped | expired.
            executed_at: UTC ISO-8601 timestamp (required when status='executed').
            fill_price:  Approximate fill price at time of execution.
            skip_reason: Human-readable reason why the signal was skipped.

        Returns:
            True if exactly one row was updated, False otherwise.
        """
        if status not in _VALID_SIGNAL_STATUSES:
            logger.error(
                "Invalid signal status '%s'. Must be one of: %s",
                status, _VALID_SIGNAL_STATUSES,
            )
            return False
        try:
            with self._write_lock, self._conn:
                cursor = self._conn.execute(
                    "UPDATE signals SET status = ?, executed_at = ?, fill_price = ?, "
                    "skip_reason = ? WHERE id = ?",
                    (status, executed_at, fill_price, skip_reason, signal_id),
                )
                updated = cursor.rowcount == 1
                if not updated:
                    logger.warning("update_signal_status: no row found for id=%d", signal_id)
                return updated
        except Exception:
            logger.exception("Failed to update signal id=%d", signal_id)
            return False

    def update_signal_exit_price(self, signal_id: int, exit_price: float) -> bool:
        """Record the exit price after a position is closed (used for P&L tracking)."""
        try:
            with self._write_lock, self._conn:
                cursor = self._conn.execute(
                    "UPDATE signals SET exit_price = ? WHERE id = ?",
                    (exit_price, signal_id),
                )
                return cursor.rowcount == 1
        except Exception:
            logger.exception("Failed to update exit_price for signal id=%d", signal_id)
            return False

    def get_articles_since(self, hours: int = 24) -> list[dict]:
        """Return all articles stored in the last `hours` hours, newest first."""
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        try:
            rows = self._conn.execute(
                "SELECT * FROM articles WHERE fetched_at >= ? ORDER BY id DESC",
                (cutoff,),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            logger.exception("Failed to fetch articles since %d hours ago", hours)
            return []

    def get_last_executed_signal(self, ticker: str) -> dict | None:
        """Return the most recent executed signal for a ticker, or None."""
        try:
            row = self._conn.execute(
                "SELECT * FROM signals WHERE ticker = ? AND status = 'executed' "
                "ORDER BY executed_at DESC LIMIT 1",
                (ticker,),
            ).fetchone()
            return dict(row) if row else None
        except Exception:
            logger.exception("Failed to fetch last executed signal for %s", ticker)
            return None

    def count_executed_today(self) -> int:
        """Count signals executed today (UTC date), keyed on executed_at not created_at."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM signals WHERE status = 'executed' AND executed_at LIKE ?",
                (f"{today}%",),
            ).fetchone()
            return row[0] if row else 0
        except Exception:
            logger.exception("Failed to count today's executed signals")
            return 0

    def count_signal_sources_since(
        self, theme: str, ticker: str, action: str, hours: int
    ) -> int:
        """
        Return the number of distinct sources that generated a signal with the
        given theme+ticker+action in the last `hours` hours.

        Used for cross-cycle multi-source corroboration: a signal is only
        executed when at least MIN_SOURCE_COUNT independent sources have
        reported the same story within the corroboration window.
        """
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        try:
            row = self._conn.execute(
                """
                SELECT COUNT(DISTINCT source) FROM signals
                WHERE theme = ? AND ticker = ? AND action = ?
                  AND created_at >= ?
                  AND source IS NOT NULL AND source != ''
                """,
                (theme, ticker, action, cutoff),
            ).fetchone()
            return row[0] if row else 0
        except Exception:
            logger.exception(
                "Failed to count signal sources for theme=%s ticker=%s action=%s",
                theme, ticker, action,
            )
            return 0

    # ------------------------------------------------------------------
    # Bot state (key-value store for persistent session metadata)
    # ------------------------------------------------------------------

    def get_state(self, key: str) -> str | None:
        """Return the stored string value for `key`, or None if absent."""
        try:
            row = self._conn.execute(
                "SELECT value FROM bot_state WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else None
        except Exception:
            logger.exception("Failed to read bot_state key=%s", key)
            return None

    def set_state(self, key: str, value: str) -> None:
        """Upsert a string value into the key-value store."""
        try:
            with self._write_lock, self._conn:
                self._conn.execute(
                    "INSERT INTO bot_state (key, value) VALUES (?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )
        except Exception:
            logger.exception("Failed to write bot_state key=%s", key)

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
        logger.debug("Database connection closed")
