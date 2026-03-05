"""
Unit tests for core/signal_gen.py — rule-based signal generator.

No external APIs, no ML models. All tests run without markers (fast).

Run with:
    python -m pytest tests/test_signal_gen.py -v
"""

import pytest


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def gen():
    from core.signal_gen import SignalGenerator
    return SignalGenerator(conviction_threshold=0.4)


def _article(
    headline: str,
    summary: str = "",
    sentiment_label: str = "positive",
    sentiment_score: float = 0.9,
    article_id: int = 1,
) -> dict:
    return {
        "id": article_id,
        "headline": headline,
        "summary": summary,
        "source": "Reuters",
        "url": "https://example.com/%d" % article_id,
        "category": "general",
        "datetime": "2026-03-04T12:00:00+00:00",
        "related": "SPY",
        "sentiment_label": sentiment_label,
        "sentiment_score": sentiment_score,
    }


# ---------------------------------------------------------------------------
# classify_theme tests
# ---------------------------------------------------------------------------

def test_classify_theme_fed_hawkish(gen):
    theme, mult = gen.classify_theme("Fed raises rates amid hawkish outlook")
    assert theme == "fed_hawkish", "Expected 'fed_hawkish', got '%s'" % theme
    assert mult > 0.0


def test_classify_theme_fed_dovish(gen):
    theme, mult = gen.classify_theme("Fed signals rate cut as inflation cools")
    assert theme == "fed_dovish", "Expected 'fed_dovish', got '%s'" % theme


def test_classify_theme_no_match(gen):
    theme, mult = gen.classify_theme("Local sports team wins championship game")
    assert theme is None, "Expected None for irrelevant text, got '%s'" % theme
    assert mult == 0.0


def test_classify_theme_returns_first_match(gen):
    # "rate hike" → fed_hawkish should win (higher priority than market_rally)
    theme, _ = gen.classify_theme("Despite rate hike, markets rally strongly")
    assert theme == "fed_hawkish"


# ---------------------------------------------------------------------------
# generate_signal — positive cases
# ---------------------------------------------------------------------------

def test_dovish_positive_generates_buy(gen):
    """Fed rate cut + positive sentiment → BUY SPY."""
    article = _article(
        "Fed cuts rates unexpectedly, markets cheer",
        sentiment_label="positive",
        sentiment_score=0.92,
    )
    signal = gen.generate_signal(article)

    assert signal is not None, "Expected a signal, got None"
    assert signal["action"] == "buy"
    assert signal["ticker"] == "SPY"
    assert signal["theme"] == "fed_dovish"
    assert 0.0 < signal["confidence"] <= 1.0


def test_hawkish_negative_generates_sell(gen):
    """Fed rate hike + negative sentiment → SELL SPY."""
    article = _article(
        "Fed raises rates aggressively, recession fears spike",
        sentiment_label="negative",
        sentiment_score=0.88,
    )
    signal = gen.generate_signal(article)

    assert signal is not None, "Expected a signal, got None"
    assert signal["action"] == "sell"
    assert signal["ticker"] == "SPY"
    assert signal["theme"] == "fed_hawkish"


def test_geopolitical_negative_generates_sell(gen):
    """Geopolitical conflict + negative sentiment → SELL SPY."""
    article = _article(
        "Military conflict escalates, global markets in turmoil",
        sentiment_label="negative",
        sentiment_score=0.85,
    )
    signal = gen.generate_signal(article)

    assert signal is not None
    assert signal["action"] == "sell"
    assert signal["theme"] == "geopolitical_risk"


# ---------------------------------------------------------------------------
# generate_signal — suppression cases
# ---------------------------------------------------------------------------

def test_no_theme_match_returns_none(gen):
    """An irrelevant article must produce no signal."""
    article = _article(
        "Celebrities spotted at weekend gala event",
        sentiment_label="positive",
        sentiment_score=0.95,
    )
    assert gen.generate_signal(article) is None


def test_no_action_for_sentiment_returns_none(gen):
    """
    Geopolitical risk + positive sentiment has no action defined → None.
    (Positive geopolitical framing is ambiguous — we skip it.)
    """
    article = _article(
        "Peace deal reached, conflict ends after long negotiations",
        sentiment_label="positive",
        sentiment_score=0.90,
    )
    # "conflict" keyword fires geopolitical_risk; positive → no action
    signal = gen.generate_signal(article)
    # The word "conflict" is in geopolitical keywords
    # actions["positive"] = None → should return None
    assert signal is None


def test_low_confidence_returns_none(gen):
    """Confidence below threshold must suppress the signal."""
    # threshold=0.4, mult=1.0 → need sentiment_score < 0.4
    article = _article(
        "Fed pivot expected by analysts, rate cuts likely",
        sentiment_label="positive",
        sentiment_score=0.3,  # 0.3 * 1.0 = 0.3 < 0.4 threshold
    )
    assert gen.generate_signal(article) is None


def test_neutral_sentiment_suppressed(gen):
    """Neutral FinBERT label → no action for most rules → None."""
    article = _article(
        "Fed holds rates steady at monthly policy meeting",
        sentiment_label="neutral",
        sentiment_score=0.70,
    )
    # "holds rates" doesn't match any keyword; neutral → no rule fires
    assert gen.generate_signal(article) is None


def test_empty_article_returns_none(gen):
    """Empty headline + summary must return None without raising."""
    article = _article("", summary="", sentiment_label="negative", sentiment_score=0.9)
    assert gen.generate_signal(article) is None


# ---------------------------------------------------------------------------
# Signal schema validation
# ---------------------------------------------------------------------------

def test_signal_schema(gen):
    """Signal dict must contain all required keys with valid types/ranges."""
    article = _article(
        "Nonfarm payrolls beat expectations, strong hiring data",
        sentiment_label="positive",
        sentiment_score=0.85,
    )
    signal = gen.generate_signal(article)

    assert signal is not None, "Expected a signal for strong jobs headline"

    for key in ("article_id", "ticker", "action", "confidence", "theme", "rationale"):
        assert key in signal, "Signal missing key '%s'. Got: %s" % (key, list(signal.keys()))

    assert signal["action"] in {"buy", "sell"}, (
        "action must be 'buy' or 'sell', got '%s'" % signal["action"]
    )
    assert 0.0 <= signal["confidence"] <= 1.0, (
        "confidence must be in [0.0, 1.0], got %.4f" % signal["confidence"]
    )
    assert isinstance(signal["rationale"], str) and len(signal["rationale"]) > 0


# ---------------------------------------------------------------------------
# Batch method
# ---------------------------------------------------------------------------

def test_generate_signals_filters_nones(gen):
    """generate_signals() must return only actionable signals."""
    articles = [
        _article("Fed cuts rates, markets surge", sentiment_label="positive",
                 sentiment_score=0.9, article_id=1),
        _article("Weekend recap: sports scores from around the league",
                 sentiment_label="positive", sentiment_score=0.8, article_id=2),
        _article("Recession fears grow as GDP contracts sharply",
                 sentiment_label="negative", sentiment_score=0.88, article_id=3),
    ]
    signals = gen.generate_signals(articles)

    assert isinstance(signals, list)
    # Article 1 (fed_dovish + positive → buy) and article 3 (recession + negative → sell)
    # Article 2 has no matching theme → filtered
    assert len(signals) == 2, (
        "Expected 2 signals (articles 1 and 3), got %d" % len(signals)
    )
    actions = {s["action"] for s in signals}
    assert "buy" in actions
    assert "sell" in actions
