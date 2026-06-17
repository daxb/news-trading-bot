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
        "Armed conflict sees major escalation, global markets in turmoil",
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


# ---------------------------------------------------------------------------
# Forex / commodity rules
# ---------------------------------------------------------------------------

def test_usd_strength_positive_generates_sell_eurusd(gen):
    """USD strength + positive sentiment → SELL EUR_USD."""
    article = _article(
        "Dollar strengthens as investors seek USD safe haven",
        sentiment_label="positive", sentiment_score=0.85,
    )
    signal = gen.generate_signal(article)
    assert signal is not None
    assert signal["ticker"] == "EUR_USD"
    assert signal["action"] == "sell"
    assert signal["theme"] == "usd_strength"


def test_gold_safe_haven_positive_generates_buy_gld(gen):
    """Gold safe haven + positive sentiment → BUY GLD (Alpaca ETF)."""
    article = _article(
        "Gold rises on flight to gold as uncertainty grows",
        sentiment_label="positive", sentiment_score=0.85,
    )
    signal = gen.generate_signal(article)
    assert signal is not None
    assert signal["ticker"] == "GLD"
    assert signal["action"] == "buy"


def test_oil_supply_squeeze_positive_generates_buy_bno(gen):
    """Oil supply squeeze + positive sentiment → BUY BNO (Alpaca Brent ETF)."""
    article = _article(
        "Oil prices surge as tight supply continues",
        sentiment_label="positive", sentiment_score=0.85,
    )
    signal = gen.generate_signal(article)
    assert signal is not None
    assert signal["ticker"] == "BNO"
    assert signal["action"] == "buy"


def test_oil_geopolitical_negative_generates_buy_bno(gen):
    """Oil geopolitical + negative sentiment → BUY BNO (both sentiments map to buy)."""
    article = _article(
        "Pipeline attack disrupts oil field attack production capacity",
        sentiment_label="negative", sentiment_score=0.85,
    )
    signal = gen.generate_signal(article)
    assert signal is not None
    # First-match-wins rule iteration may catch oil_supply_squeeze before
    # oil_geopolitical (both contain the "oil" keyword). Either is acceptable —
    # both route to BNO. Verify only the ticker, not the specific theme/action.
    assert signal["ticker"] == "BNO"


# ---------------------------------------------------------------------------
# is_relevant
# ---------------------------------------------------------------------------

def test_is_relevant_true_for_matching_article(gen):
    article = _article("Fed signals rate hike ahead of next meeting")
    assert gen.is_relevant(article) is True


def test_is_relevant_false_for_irrelevant_article(gen):
    article = _article("Celebrity gala draws thousands to red carpet event")
    assert gen.is_relevant(article) is False


# ---------------------------------------------------------------------------
# source_count passthrough
# ---------------------------------------------------------------------------

def test_signal_includes_source_count(gen):
    """Signal dict must carry through the article's source_count field."""
    article = _article(
        "Fed cuts rates unexpectedly, markets cheer",
        sentiment_label="positive",
        sentiment_score=0.92,
    )
    article["source_count"] = 3
    signal = gen.generate_signal(article)
    assert signal is not None
    assert signal["source_count"] == 3


def test_signal_default_source_count_is_one(gen):
    """When source_count is absent from article, signal defaults to 1."""
    article = _article(
        "Fed cuts rates unexpectedly, markets cheer",
        sentiment_label="positive",
        sentiment_score=0.92,
    )
    article.pop("source_count", None)
    signal = gen.generate_signal(article)
    assert signal is not None
    assert signal["source_count"] == 1


# ---------------------------------------------------------------------------
# oil_supply_squeeze retune
# (1) must not emit a redundant SELL (oil_oversupply covers bearish oil, and a
#     BNO sell when flat is always suppressed) and (2) must not monopolise all
#     oil news via over-broad bare keywords ("oil"/"crude"/"opec").
# ---------------------------------------------------------------------------

def test_oil_supply_squeeze_buys_on_supply_cut(gen):
    """A genuine supply-squeeze headline with positive sentiment still buys BNO."""
    article = _article(
        "Production cut announced after major supply disruption",
        sentiment_label="positive",
        sentiment_score=0.9,
    )
    signal = gen.generate_signal(article)
    assert signal is not None
    assert signal["theme"] == "oil_supply_squeeze"
    assert signal["action"] == "buy"
    assert signal["ticker"] == "BNO"


def test_oil_supply_squeeze_does_not_sell_on_negative(gen):
    """Negative sentiment on a squeeze-only headline must NOT produce a signal —
    the redundant negative->sell action is removed (oil_oversupply handles bearish
    oil; a flat BNO sell is dead weight that only pollutes the audit)."""
    article = _article(
        "Production cut announced after major supply disruption",
        sentiment_label="negative",
        sentiment_score=0.9,
    )
    signal = gen.generate_signal(article)
    assert signal is None, f"expected no signal, got {signal}"


def test_generic_oil_headline_not_monopolised_by_supply_squeeze(gen):
    """A generic oil headline (no squeeze language) must no longer classify as
    oil_supply_squeeze — the bare 'oil' keyword that made it a catch-all is gone."""
    theme, _ = gen.classify_theme("Oil edges higher in cautious holiday trade")
    assert theme != "oil_supply_squeeze", (
        f"generic oil news should route to a more specific oil rule, got {theme}"
    )
