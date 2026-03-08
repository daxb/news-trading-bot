"""
Smoke tests for core/sentiment.py — FinBERT sentiment scorer.

Tests are marked `slow` because the model download is ~440 MB on first run
and inference takes a few seconds even on CPU.

Run with:
    python -m pytest tests/test_sentiment.py -v -m slow
"""

import pytest


@pytest.fixture(scope="module")
def analyzer():
    """Load FinBERT once for the entire test session."""
    from core.sentiment import SentimentAnalyzer
    return SentimentAnalyzer()


# ---------------------------------------------------------------------------
# Sentiment direction tests
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_positive_headline(analyzer):
    """
    A clearly positive financial headline must be classified as positive
    with confidence > 0.5.
    """
    result = analyzer.score("Markets rally on strong jobs report, stocks surge to record highs")

    assert result["label"] == "positive", (
        "Expected 'positive', got '%s' (score=%.4f)" % (result["label"], result["score"])
    )
    assert result["score"] > 0.5, (
        "Confidence %.4f is too low for a clearly positive headline" % result["score"]
    )


@pytest.mark.slow
def test_negative_headline(analyzer):
    """
    A clearly negative financial headline must be classified as negative
    with confidence > 0.5.
    """
    result = analyzer.score("Fed raises rates aggressively, recession fears mount, markets crash")

    assert result["label"] == "negative", (
        "Expected 'negative', got '%s' (score=%.4f)" % (result["label"], result["score"])
    )
    assert result["score"] > 0.5, (
        "Confidence %.4f is too low for a clearly negative headline" % result["score"]
    )


# ---------------------------------------------------------------------------
# Schema / contract tests
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_score_schema(analyzer):
    """
    score() must always return a dict with 'label' in the allowed set
    and 'score' in [0.0, 1.0].
    """
    result = analyzer.score("The central bank held rates steady at its monthly meeting.")

    assert isinstance(result, dict), "score() must return a dict"
    assert "label" in result, "Result missing 'label' key. Got: %s" % result
    assert "score" in result, "Result missing 'score' key. Got: %s" % result
    assert result["label"] in {"positive", "negative", "neutral"}, (
        "label must be one of positive/negative/neutral, got '%s'" % result["label"]
    )
    assert 0.0 <= result["score"] <= 1.0, (
        "score must be in [0.0, 1.0], got %.4f" % result["score"]
    )


@pytest.mark.slow
def test_empty_string_returns_safe_default(analyzer):
    """
    Empty input must return the safe default without raising.
    """
    result = analyzer.score("")

    assert result == {"label": "neutral", "score": 0.0}, (
        "Expected safe default for empty input, got: %s" % result
    )


@pytest.mark.slow
def test_score_articles_batch(analyzer):
    """score_articles() must return same-length list with sentiment keys."""
    articles = [
        {"id": 1, "headline": "Markets rally", "summary": "", "source": "x",
         "url": "", "category": "", "datetime": None, "related": ""},
        {"id": 2, "headline": "Oil prices crash", "summary": "", "source": "x",
         "url": "", "category": "", "datetime": None, "related": ""},
    ]
    result = analyzer.score_articles(articles)
    assert len(result) == 2
    for a in result:
        assert "sentiment_label" in a
        assert "sentiment_score" in a


@pytest.mark.slow
def test_score_articles_empty_input(analyzer):
    """score_articles([]) must return []."""
    assert analyzer.score_articles([]) == []


@pytest.mark.slow
def test_score_article_preserves_keys(analyzer):
    """
    score_article() must return a new dict that contains all original
    article keys plus 'sentiment_label' and 'sentiment_score'.
    The original dict must not be mutated.
    """
    article = {
        "id": 1,
        "headline": "Company beats earnings expectations, raises full-year guidance",
        "summary": "Shares jumped 8% after the company reported record quarterly profits.",
        "source": "Reuters",
        "url": "https://example.com/article/1",
        "category": "general",
        "datetime": "2026-03-04T12:00:00+00:00",
        "related": "AAPL",
    }
    original_keys = set(article.keys())

    scored = analyzer.score_article(article)

    # Original must be untouched
    assert set(article.keys()) == original_keys, "score_article() must not mutate the input dict"

    # All original keys must be preserved in the output
    for key in original_keys:
        assert key in scored, "Scored article missing original key '%s'" % key
        assert scored[key] == article[key], (
            "Value for '%s' changed: expected %r, got %r" % (key, article[key], scored[key])
        )

    # Sentiment keys must be present and valid
    assert "sentiment_label" in scored, "Scored article missing 'sentiment_label'"
    assert "sentiment_score" in scored, "Scored article missing 'sentiment_score'"
    assert scored["sentiment_label"] in {"positive", "negative", "neutral"}, (
        "sentiment_label must be positive/negative/neutral, got '%s'" % scored["sentiment_label"]
    )
    assert 0.0 <= scored["sentiment_score"] <= 1.0, (
        "sentiment_score must be in [0.0, 1.0], got %.4f" % scored["sentiment_score"]
    )
