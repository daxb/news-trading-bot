"""
Unit tests for core/db.py — SQLite repository.

Uses an in-memory database (:memory:) so no files are created and
no API keys are required. These tests run without any marks (fast).

Run with:
    python -m pytest tests/test_db.py -v
"""

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    """Fresh in-memory Database for each test."""
    from core.db import Database
    database = Database(db_path=":memory:")
    yield database
    database.close()


def _make_article(article_id: int = 1, sentiment_label: str = "positive") -> dict:
    """Minimal article dict matching the schema from news.py + sentiment.py."""
    return {
        "id": article_id,
        "headline": "Markets rally on strong jobs report",
        "summary": "Stocks surged after better-than-expected employment data.",
        "source": "Reuters",
        "url": "https://example.com/article/%d" % article_id,
        "category": "general",
        "datetime": "2026-03-04T12:00:00+00:00",
        "related": "SPY",
        "sentiment_label": sentiment_label,
        "sentiment_score": 0.92,
    }


def _make_signal(article_id: int = 1) -> dict:
    """Minimal signal dict."""
    return {
        "article_id": article_id,
        "ticker": "SPY",
        "action": "buy",
        "confidence": 0.75,
        "theme": "risk_on",
        "rationale": "Strong jobs → equities bullish",
    }


# ---------------------------------------------------------------------------
# Schema / init tests
# ---------------------------------------------------------------------------

def test_db_initializes(db):
    """Database must connect and create tables without raising."""
    # If __init__ completed, the fixture succeeded — just verify tables exist
    from core.db import Database
    tables = db._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    table_names = {row[0] for row in tables}
    assert "articles" in table_names, "articles table not created"
    assert "signals" in table_names, "signals table not created"


# ---------------------------------------------------------------------------
# Article tests
# ---------------------------------------------------------------------------

def test_save_article_returns_rowid(db):
    """save_article() must return a positive integer rowid."""
    rowid = db.save_article(_make_article())
    assert isinstance(rowid, int), "Expected int rowid, got %s" % type(rowid)
    assert rowid > 0, "rowid must be > 0, got %d" % rowid


def test_save_article_dedup(db):
    """Saving the same article_id twice must silently skip and return None."""
    article = _make_article(article_id=42)
    first = db.save_article(article)
    second = db.save_article(article)

    assert first is not None, "First insert must return a rowid"
    assert second is None, "Duplicate insert must return None (INSERT OR IGNORE)"


def test_article_exists(db):
    """article_exists() must return True after insert, False before."""
    assert db.article_exists(99) is False, "article_exists() must be False before insert"
    db.save_article(_make_article(article_id=99))
    assert db.article_exists(99) is True, "article_exists() must be True after insert"


def test_get_articles_returns_list(db):
    """get_articles() must return a list of dicts with expected keys."""
    db.save_article(_make_article(article_id=1))
    db.save_article(_make_article(article_id=2))

    articles = db.get_articles(limit=10)

    assert isinstance(articles, list), "get_articles() must return a list"
    assert len(articles) == 2, "Expected 2 articles, got %d" % len(articles)

    for article in articles:
        for key in ("article_id", "headline", "sentiment_label", "sentiment_score", "fetched_at"):
            assert key in article, "Article missing key '%s'. Got: %s" % (key, list(article.keys()))


def test_get_articles_sentiment_filter(db):
    """get_articles(sentiment_label=...) must filter correctly."""
    db.save_article(_make_article(article_id=1, sentiment_label="positive"))
    db.save_article(_make_article(article_id=2, sentiment_label="negative"))
    db.save_article(_make_article(article_id=3, sentiment_label="positive"))

    positive = db.get_articles(sentiment_label="positive")
    negative = db.get_articles(sentiment_label="negative")

    assert len(positive) == 2, "Expected 2 positive articles, got %d" % len(positive)
    assert len(negative) == 1, "Expected 1 negative article, got %d" % len(negative)
    assert all(a["sentiment_label"] == "positive" for a in positive)
    assert all(a["sentiment_label"] == "negative" for a in negative)


def test_get_articles_limit(db):
    """get_articles(limit=N) must respect the limit."""
    for i in range(5):
        db.save_article(_make_article(article_id=i + 1))

    result = db.get_articles(limit=3)
    assert len(result) == 3, "Expected 3 articles with limit=3, got %d" % len(result)


# ---------------------------------------------------------------------------
# Signal tests
# ---------------------------------------------------------------------------

def test_save_signal_returns_rowid(db):
    """save_signal() must return a positive integer rowid."""
    db.save_article(_make_article())
    rowid = db.save_signal(_make_signal())

    assert isinstance(rowid, int), "Expected int rowid, got %s" % type(rowid)
    assert rowid > 0, "rowid must be > 0, got %d" % rowid


def test_get_pending_signals(db):
    """get_pending_signals() must return newly saved signals."""
    db.save_article(_make_article())
    db.save_signal(_make_signal())

    pending = db.get_pending_signals()

    assert isinstance(pending, list), "get_pending_signals() must return a list"
    assert len(pending) == 1, "Expected 1 pending signal, got %d" % len(pending)

    signal = pending[0]
    for key in ("id", "ticker", "action", "confidence", "status"):
        assert key in signal, "Signal missing key '%s'. Got: %s" % (key, list(signal.keys()))
    assert signal["status"] == "pending"
    assert signal["ticker"] == "SPY"


def test_update_signal_status_executed(db):
    """update_signal_status('executed') must remove signal from pending list."""
    db.save_article(_make_article())
    signal_id = db.save_signal(_make_signal())

    result = db.update_signal_status(signal_id, "executed", executed_at="2026-03-04T13:00:00+00:00")

    assert result is True, "update_signal_status() must return True on success"
    assert db.get_pending_signals() == [], "Executed signal must not appear in pending list"


def test_update_signal_status_invalid(db):
    """update_signal_status() must return False for an unknown status."""
    db.save_article(_make_article())
    signal_id = db.save_signal(_make_signal())

    result = db.update_signal_status(signal_id, "launched_rocket")

    assert result is False, "Invalid status must return False"
    # Signal must remain pending (not corrupted)
    assert len(db.get_pending_signals()) == 1


def test_update_signal_status_missing_id(db):
    """update_signal_status() must return False for a non-existent signal id."""
    result = db.update_signal_status(9999, "skipped")
    assert result is False, "Missing signal id must return False"


# ---------------------------------------------------------------------------
# Time-window and state tests
# ---------------------------------------------------------------------------

def test_get_recent_headlines(db):
    """get_recent_headlines() must return headlines within the time window."""
    db.save_article(_make_article(article_id=1))
    db.save_article(_make_article(article_id=2))
    headlines = db.get_recent_headlines(hours=4)
    assert len(headlines) == 2
    assert all(isinstance(h, str) for h in headlines)


def test_get_recent_headlines_excludes_empty(db):
    """Articles with empty headlines are excluded by the query."""
    article = _make_article(article_id=10)
    article["headline"] = ""
    db.save_article(article)
    db.save_article(_make_article(article_id=11))
    headlines = db.get_recent_headlines(hours=4)
    assert len(headlines) == 1


def test_get_articles_since(db):
    """get_articles_since() must return articles within the time window."""
    db.save_article(_make_article(article_id=1))
    articles = db.get_articles_since(hours=24)
    assert len(articles) == 1


def test_get_signals_since(db):
    """get_signals_since() must return signals within the time window."""
    db.save_article(_make_article())
    db.save_signal(_make_signal())
    signals = db.get_signals_since(hours=1)
    assert len(signals) == 1


def test_count_executed_today(db):
    """count_executed_today() must count only today's executed signals."""
    from datetime import datetime, timezone
    db.save_article(_make_article(article_id=1))
    db.save_article(_make_article(article_id=2))

    # Execute one today
    sid1 = db.save_signal(_make_signal(article_id=1))
    db.update_signal_status(sid1, "executed", executed_at=datetime.now(timezone.utc).isoformat())

    # Leave another as pending
    db.save_signal(_make_signal(article_id=2))

    assert db.count_executed_today() == 1


def test_count_signal_sources_since(db):
    """count_signal_sources_since() must count distinct sources."""
    db.save_article(_make_article(article_id=1))
    db.save_article(_make_article(article_id=2))
    db.save_signal({**_make_signal(article_id=1), "source": "Reuters", "theme": "fed_hawkish"})
    db.save_signal({**_make_signal(article_id=2), "source": "AP", "theme": "fed_hawkish"})
    count = db.count_signal_sources_since("fed_hawkish", "SPY", "buy", hours=1)
    assert count == 2


def test_get_set_state(db):
    """set_state() + get_state() must round-trip a string value."""
    db.set_state("test_key", "test_value")
    assert db.get_state("test_key") == "test_value"


def test_set_state_upsert(db):
    """set_state() with the same key twice must overwrite."""
    db.set_state("key", "first")
    db.set_state("key", "second")
    assert db.get_state("key") == "second"


def test_update_signal_exit_price(db):
    """update_signal_exit_price() must persist the exit price."""
    db.save_article(_make_article())
    sid = db.save_signal(_make_signal())
    db.update_signal_exit_price(sid, 450.0)
    signals = db.get_signals(limit=1)
    assert signals[0]["exit_price"] == 450.0


def test_get_last_executed_signal(db):
    """get_last_executed_signal() must return the most recent executed signal."""
    db.save_article(_make_article(article_id=1))
    db.save_article(_make_article(article_id=2))
    sid1 = db.save_signal(_make_signal(article_id=1))
    sid2 = db.save_signal(_make_signal(article_id=2))
    db.update_signal_status(sid1, "executed", executed_at="2026-03-04T12:00:00+00:00")
    db.update_signal_status(sid2, "executed", executed_at="2026-03-04T13:00:00+00:00")

    result = db.get_last_executed_signal("SPY")
    assert result is not None
    assert result["id"] == sid2
