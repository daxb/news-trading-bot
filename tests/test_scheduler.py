"""
Unit tests for core/scheduler.py — BotScheduler poll logic.

All external collaborators (NewsClient, SentimentAnalyzer, SignalGenerator,
Database) are replaced with fakes so these tests are fast and require no
API keys, no network, and no ML models.

Run with:
    python -m pytest tests/test_scheduler.py -v
"""

import pytest

# core.scheduler transitively imports oandapyV20 and feedparser
pytest.importorskip("oandapyV20", reason="oandapyV20 not installed")
pytest.importorskip("feedparser", reason="feedparser not installed")


# ---------------------------------------------------------------------------
# Fakes / stubs
# ---------------------------------------------------------------------------

class FakeNews:
    def __init__(self, articles=None):
        self.articles = articles or []
        self.call_count = 0

    def get_general_news(self):
        self.call_count += 1
        return self.articles


class FakeSentiment:
    """Passes articles through, adding fixed sentiment fields."""
    def score_articles(self, articles):
        return [
            {**a, "sentiment_label": "positive", "sentiment_score": 0.9}
            for a in articles
        ]


class FakeSignalGen:
    def __init__(self, signals=None, relevant=True):
        self._signals = signals or []
        self._relevant = relevant

    def generate_signals(self, articles):
        return self._signals

    def is_relevant(self, article):
        return self._relevant


class FakeDB:
    def __init__(self, existing_ids=None):
        self._existing = set(existing_ids or [])
        self.saved_articles = []
        self.saved_signals = []

    def article_exists(self, article_id):
        return article_id in self._existing

    def save_article(self, article):
        self.saved_articles.append(article)
        return len(self.saved_articles)  # fake rowid

    def save_signal(self, signal):
        self.saved_signals.append(signal)
        return len(self.saved_signals)

    def has_recent_signal(self, ticker=None, action=None, theme=None, minutes=None):
        # Default: no prior matching signal — let signals pass through cooldown.
        return False

    def expire_stale_pending(self, minutes=None):
        return 0

    def get_recent_headlines(self, hours=4):
        return []

    def update_signal_status(self, signal_id, status, executed_at=None, fill_price=None, skip_reason=None):
        return True

    def count_signal_sources_since(self, theme, ticker, action, hours):
        return 1

    def close(self):
        pass


# ---------------------------------------------------------------------------
# Helper: build a scheduler with injected fakes
# ---------------------------------------------------------------------------

def _make_scheduler(news=None, sentiment=None, signals=None, db=None):
    """Construct a BotScheduler with all components replaced by fakes.

    The scheduler grew collaborators over time; this helper sets the minimum
    set required for _poll() to run without AttributeError. Tests that exercise
    risk/broker/forex paths should use _make_extended_scheduler.
    """
    from core.scheduler import BotScheduler
    bot = BotScheduler.__new__(BotScheduler)  # skip __init__ (would load real models)
    import threading
    bot._stop_event = threading.Event()
    bot._news = news or FakeNews()
    bot._rss = FakeRSS()
    bot._sentiment = sentiment or FakeSentiment()
    bot._signals = signals or FakeSignalGen()
    bot._db = db or FakeDB()
    bot._broker = FakeBrokerForScheduler()
    bot._risk = FakeRiskManager()
    bot._forex = None
    bot._forex_risk = None
    bot._macro_ctx = FakeMacroCtx()
    bot._exit_mgr = FakeExitMgr()
    return bot


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_poll_saves_new_articles():
    """New articles from the news client must be scored and persisted."""
    articles = [
        {"id": 1, "headline": "Fed cuts rates", "summary": "", "source": "Reuters",
         "url": "", "category": "general", "datetime": None, "related": ""},
        {"id": 2, "headline": "Markets surge", "summary": "", "source": "AP",
         "url": "", "category": "general", "datetime": None, "related": ""},
    ]
    db = FakeDB(existing_ids=[])
    bot = _make_scheduler(news=FakeNews(articles), db=db)

    bot._poll()

    assert len(db.saved_articles) == 2, (
        "Expected 2 saved articles, got %d" % len(db.saved_articles)
    )


def test_poll_skips_duplicate_articles():
    """Articles already in the DB must not be re-scored or re-saved."""
    articles = [
        {"id": 1, "headline": "Old news", "summary": "", "source": "Reuters",
         "url": "", "category": "general", "datetime": None, "related": ""},
        {"id": 2, "headline": "New news", "summary": "", "source": "AP",
         "url": "", "category": "general", "datetime": None, "related": ""},
    ]
    db = FakeDB(existing_ids=[1])  # article 1 already seen
    bot = _make_scheduler(news=FakeNews(articles), db=db)

    bot._poll()

    assert len(db.saved_articles) == 1, (
        "Expected only 1 new article saved (id=2), got %d" % len(db.saved_articles)
    )
    assert db.saved_articles[0]["id"] == 2


def test_poll_saves_signals():
    """Signals returned by the rules engine must be persisted to the DB."""
    articles = [
        {"id": 1, "headline": "Fed pivot", "summary": "", "source": "Reuters",
         "url": "", "category": "general", "datetime": None, "related": ""},
    ]
    fake_signal = {
        "article_id": 1, "ticker": "SPY", "action": "buy",
        "confidence": 0.85, "theme": "fed_dovish", "rationale": "test",
    }
    db = FakeDB()
    bot = _make_scheduler(
        news=FakeNews(articles),
        signals=FakeSignalGen([fake_signal]),
        db=db,
    )

    bot._poll()

    assert len(db.saved_signals) == 1
    assert db.saved_signals[0]["ticker"] == "SPY"
    assert db.saved_signals[0]["action"] == "buy"


def test_poll_no_articles_is_a_noop():
    """An empty news response must not touch the DB at all."""
    db = FakeDB()
    bot = _make_scheduler(news=FakeNews([]), db=db)

    bot._poll()

    assert db.saved_articles == []
    assert db.saved_signals == []


def test_poll_news_exception_does_not_crash():
    """If the news client raises, _poll() must catch it and return cleanly."""
    class BrokenNews:
        def get_general_news(self):
            raise RuntimeError("network timeout")

    db = FakeDB()
    bot = _make_scheduler(news=BrokenNews(), db=db)

    # Must not raise
    bot._poll()

    assert db.saved_articles == []


def test_poll_all_duplicates_skips_sentiment():
    """If every article is a duplicate, sentiment scoring must not be called."""
    articles = [{"id": 10, "headline": "Old", "summary": "", "source": "x",
                 "url": "", "category": "", "datetime": None, "related": ""}]

    class FailSentiment:
        def score_articles(self, articles):
            raise AssertionError("score_articles should not be called for all-duplicate poll")

    db = FakeDB(existing_ids=[10])
    bot = _make_scheduler(news=FakeNews(articles), sentiment=FailSentiment(), db=db)

    bot._poll()  # must not raise


# ---------------------------------------------------------------------------
# Extended pipeline tests
# ---------------------------------------------------------------------------

class FakeRSS:
    """Stub RSS client."""
    def __init__(self, articles=None):
        self.articles = articles or []
    def get_articles(self):
        return self.articles


class FakeRiskManager:
    def __init__(self, approved=True, reason=""):
        self._approved = approved
        self._reason = reason
    def can_trade(self, ticker=None, action=None):
        return self._approved, self._reason
    def position_qty(self, ticker):
        return 10.0 if self._approved else 0.0


class FakeMacroCtx:
    def tick(self): pass
    def adjust_signals(self, signals): return signals


class FakeExitMgr:
    def check_exits(self): pass


class FakeBrokerForScheduler:
    def __init__(self, has_position=True):
        self._has_position = has_position
        self.submitted_orders = []
    def get_position(self, ticker):
        return {"symbol": ticker, "qty": 10} if self._has_position else None
    def get_latest_price(self, ticker):
        return 500.0
    def submit_market_order(self, ticker, qty, side):
        order = {"id": "test-order", "status": "filled"}
        self.submitted_orders.append(order)
        return order


def _make_extended_scheduler(
    news=None, rss=None, sentiment=None, signals=None, db=None,
    risk=None, broker=None, forex=None, forex_risk=None,
    macro_ctx=None, exit_mgr=None,
):
    from core.scheduler import BotScheduler
    import threading
    bot = BotScheduler.__new__(BotScheduler)
    bot._stop_event = threading.Event()
    bot._news = news or FakeNews()
    bot._rss = rss or FakeRSS()
    bot._sentiment = sentiment or FakeSentiment()
    bot._signals = signals or FakeSignalGen()
    bot._db = db or FakeDB()
    bot._broker = broker or FakeBrokerForScheduler()
    bot._risk = risk or FakeRiskManager()
    bot._forex = forex
    bot._forex_risk = forex_risk
    bot._macro_ctx = macro_ctx or FakeMacroCtx()
    bot._exit_mgr = exit_mgr or FakeExitMgr()
    return bot


def test_poll_with_rss_articles():
    """RSS articles must be fetched and contribute to the pipeline."""
    finnhub = [{"id": 1, "headline": "Fed cuts rates", "summary": "", "source": "Finnhub",
                "url": "", "category": "general", "datetime": None, "related": ""}]
    rss = [{"id": 2, "headline": "Markets surge on rate cut", "summary": "", "source": "BBC",
            "url": "", "category": "rss", "datetime": None, "related": ""}]
    db = FakeDB()
    bot = _make_extended_scheduler(news=FakeNews(finnhub), rss=FakeRSS(rss), db=db)
    bot._poll()
    assert len(db.saved_articles) == 2


def test_poll_risk_check_blocks_execution():
    """Risk manager returning False must prevent order execution."""
    articles = [{"id": 1, "headline": "Fed cuts rates", "summary": "", "source": "Reuters",
                 "url": "", "category": "general", "datetime": None, "related": ""}]
    signal = {"article_id": 1, "ticker": "SPY", "action": "buy",
              "confidence": 0.85, "theme": "fed_dovish", "rationale": "test"}
    db = FakeDB()
    # Need a DB that supports update_signal_status for skip recording
    db.update_signal_status = lambda *a, **kw: True
    db.get_recent_headlines = lambda **kw: []
    db.count_signal_sources_since = lambda *a, **kw: 1

    risk = FakeRiskManager(approved=False, reason="daily limit")
    broker = FakeBrokerForScheduler()
    bot = _make_extended_scheduler(
        news=FakeNews(articles),
        signals=FakeSignalGen([signal]),
        db=db, risk=risk, broker=broker,
    )
    bot._poll()
    assert len(broker.submitted_orders) == 0


def test_poll_equity_sell_no_position_skips():
    """Equity sell signal with no existing position must be skipped."""
    articles = [{"id": 1, "headline": "Recession fears mount", "summary": "", "source": "Reuters",
                 "url": "", "category": "general", "datetime": None, "related": ""}]
    signal = {"article_id": 1, "ticker": "SPY", "action": "sell",
              "confidence": 0.85, "theme": "recession_risk", "rationale": "test"}
    db = FakeDB()
    db.update_signal_status = lambda *a, **kw: True
    db.get_recent_headlines = lambda **kw: []
    db.count_signal_sources_since = lambda *a, **kw: 1
    db.has_recent_signal = lambda **kw: False

    broker = FakeBrokerForScheduler(has_position=False)
    bot = _make_extended_scheduler(
        news=FakeNews(articles),
        signals=FakeSignalGen([signal]),
        db=db, broker=broker,
    )
    bot._poll()
    assert len(broker.submitted_orders) == 0


# ---------------------------------------------------------------------------
# Cooldown tests — use the real :memory: Database fixture so we exercise the
# actual has_recent_signal SQL path, not a stub.
# ---------------------------------------------------------------------------

def test_poll_suppresses_duplicate_signal_within_cooldown(monkeypatch):
    """Two signals with same (ticker, action, theme) in one poll: first goes
    through, second is saved as skipped with reason='cooldown_active'."""
    from config import settings
    from core.db import Database

    monkeypatch.setattr(settings, "SIGNAL_COOLDOWN_ENABLED", True)
    monkeypatch.setattr(settings, "SIGNAL_COOLDOWN_MINUTES", 30)

    db = Database(db_path=":memory:")
    try:
        articles = [
            {"id": 1, "headline": "Iran war escalates", "summary": "", "source": "Reuters",
             "url": "", "category": "general", "datetime": None, "related": ""},
            {"id": 2, "headline": "Middle East tensions rise sharply", "summary": "", "source": "AP",
             "url": "", "category": "general", "datetime": None, "related": ""},
        ]
        signals = [
            {"article_id": 1, "ticker": "SPY", "action": "sell",
             "confidence": 0.85, "theme": "geopolitical_risk", "rationale": "test"},
            {"article_id": 2, "ticker": "SPY", "action": "sell",
             "confidence": 0.85, "theme": "geopolitical_risk", "rationale": "test"},
        ]
        bot = _make_extended_scheduler(
            news=FakeNews(articles),
            signals=FakeSignalGen(signals),
            db=db,
        )
        bot._poll()

        rows = db.get_signals(limit=10)
        assert len(rows) == 2, f"Expected 2 signals saved, got {len(rows)}"

        cooled = [s for s in rows if s["skip_reason"] == "cooldown_active"]
        assert len(cooled) == 1, (
            f"Expected exactly 1 cooldown-suppressed signal, got {len(cooled)}: {rows}"
        )
        assert cooled[0]["status"] == "skipped"

        non_cooled = [s for s in rows if s["skip_reason"] != "cooldown_active"]
        assert len(non_cooled) == 1
        assert non_cooled[0]["status"] in ("pending", "executed"), (
            "First signal must be pending or executed, not cooldown-suppressed"
        )
    finally:
        db.close()


def test_poll_cooldown_disabled_via_env(monkeypatch):
    """With SIGNAL_COOLDOWN_ENABLED=False, both duplicate signals proceed normally."""
    from config import settings
    from core.db import Database

    monkeypatch.setattr(settings, "SIGNAL_COOLDOWN_ENABLED", False)

    db = Database(db_path=":memory:")
    try:
        articles = [
            {"id": 1, "headline": "Iran war escalates", "summary": "", "source": "Reuters",
             "url": "", "category": "general", "datetime": None, "related": ""},
            {"id": 2, "headline": "Middle East tensions rise sharply", "summary": "", "source": "AP",
             "url": "", "category": "general", "datetime": None, "related": ""},
        ]
        signals = [
            {"article_id": 1, "ticker": "SPY", "action": "sell",
             "confidence": 0.85, "theme": "geopolitical_risk", "rationale": "test"},
            {"article_id": 2, "ticker": "SPY", "action": "sell",
             "confidence": 0.85, "theme": "geopolitical_risk", "rationale": "test"},
        ]
        bot = _make_extended_scheduler(
            news=FakeNews(articles),
            signals=FakeSignalGen(signals),
            db=db,
        )
        bot._poll()

        rows = db.get_signals(limit=10)
        assert len(rows) == 2
        cooled = [s for s in rows if s["skip_reason"] == "cooldown_active"]
        assert len(cooled) == 0, "Cooldown should be disabled — no rows should be cooldown-suppressed"
    finally:
        db.close()


def test_poll_cooldown_allows_different_theme(monkeypatch):
    """Same ticker+action but different theme must not trigger cooldown."""
    from config import settings
    from core.db import Database

    monkeypatch.setattr(settings, "SIGNAL_COOLDOWN_ENABLED", True)
    monkeypatch.setattr(settings, "SIGNAL_COOLDOWN_MINUTES", 30)

    db = Database(db_path=":memory:")
    try:
        articles = [
            {"id": 1, "headline": "Recession fears mount", "summary": "", "source": "Reuters",
             "url": "", "category": "general", "datetime": None, "related": ""},
            {"id": 2, "headline": "Fed signals hawkish stance", "summary": "", "source": "AP",
             "url": "", "category": "general", "datetime": None, "related": ""},
        ]
        signals = [
            {"article_id": 1, "ticker": "SPY", "action": "sell",
             "confidence": 0.85, "theme": "recession_risk", "rationale": "test"},
            {"article_id": 2, "ticker": "SPY", "action": "sell",
             "confidence": 0.85, "theme": "fed_hawkish", "rationale": "test"},
        ]
        bot = _make_extended_scheduler(
            news=FakeNews(articles),
            signals=FakeSignalGen(signals),
            db=db,
        )
        bot._poll()

        rows = db.get_signals(limit=10)
        cooled = [s for s in rows if s["skip_reason"] == "cooldown_active"]
        assert len(cooled) == 0, (
            f"Different themes must not collide. Got cooldown rows: {cooled}"
        )
    finally:
        db.close()
