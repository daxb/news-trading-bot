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
"""

import logging
import os
import sqlite3
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
    executed_at TEXT
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
        self._init_schema()
        logger.info("Database ready at %s", path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(_CREATE_ARTICLES)
            self._conn.execute(_CREATE_SIGNALS)

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
            with self._conn:
                cursor = self._conn.execute(sql, params)
                rowid = cursor.lastrowid if cursor.rowcount > 0 else None
                if rowid:
                    logger.debug("Saved article id=%s rowid=%d", params["article_id"], rowid)
                return rowid
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
                 status, created_at, executed_at)
            VALUES
                (:article_id, :ticker, :action, :confidence, :theme, :rationale,
                 :status, :created_at, :executed_at)
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
        }
        try:
            with self._conn:
                cursor = self._conn.execute(sql, params)
                logger.debug(
                    "Saved signal: %s %s (confidence=%.2f)",
                    params["action"], params["ticker"], params["confidence"],
                )
                return cursor.lastrowid
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
    ) -> bool:
        """
        Update a signal's status.

        Args:
            signal_id:   The signal's primary key.
            status:      One of pending | executed | skipped | expired.
            executed_at: UTC ISO-8601 timestamp (required when status='executed').

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
            with self._conn:
                cursor = self._conn.execute(
                    "UPDATE signals SET status = ?, executed_at = ? WHERE id = ?",
                    (status, executed_at, signal_id),
                )
                updated = cursor.rowcount == 1
                if not updated:
                    logger.warning("update_signal_status: no row found for id=%d", signal_id)
                return updated
        except Exception:
            logger.exception("Failed to update signal id=%d", signal_id)
            return False

    def count_executed_today(self) -> int:
        """Count signals executed today (UTC date)."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM signals WHERE status = 'executed' AND created_at LIKE ?",
                (f"{today}%",),
            ).fetchone()
            return row[0] if row else 0
        except Exception:
            logger.exception("Failed to count today's executed signals")
            return 0

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
        logger.debug("Database connection closed")
