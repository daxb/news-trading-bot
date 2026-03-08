"""
Unit tests for core/dedup.py — headline similarity deduplication.

Pure functions with no external dependencies — no API keys, no network.

Run with:
    python -m pytest tests/test_dedup.py -v
"""

import pytest

from core.dedup import _tokenize, _jaccard, deduplicate


# ---------------------------------------------------------------------------
# _tokenize
# ---------------------------------------------------------------------------

def test_tokenize_basic():
    tokens = _tokenize("Fed cuts rates")
    assert "fed" in tokens
    assert "cuts" in tokens
    assert "rates" in tokens


def test_tokenize_strips_punctuation():
    tokens = _tokenize("U.S. rates!")
    # Punctuation removed; "us" has len 2 so dropped
    assert all(c.isalnum() for t in tokens for c in t)


def test_tokenize_removes_stopwords():
    tokens = _tokenize("the Fed is cutting rates")
    assert "the" not in tokens
    assert "is" not in tokens


def test_tokenize_removes_short_tokens():
    tokens = _tokenize("Fed is on a big rate cut")
    # "is", "on", "a" are stopwords/short; "big" len=3 passes
    for t in tokens:
        assert len(t) > 2


def test_tokenize_case_insensitive():
    upper = _tokenize("FED CUTS RATES")
    lower = _tokenize("fed cuts rates")
    assert upper == lower


# ---------------------------------------------------------------------------
# _jaccard
# ---------------------------------------------------------------------------

def test_jaccard_identical():
    s = frozenset({"fed", "cuts", "rates"})
    assert _jaccard(s, s) == 1.0


def test_jaccard_disjoint():
    a = frozenset({"fed", "cuts"})
    b = frozenset({"oil", "rises"})
    assert _jaccard(a, b) == 0.0


def test_jaccard_partial_overlap():
    a = frozenset({"fed", "cuts", "rates"})
    b = frozenset({"fed", "hikes", "rates"})
    # intersection = {"fed", "rates"} = 2, union = 4
    assert _jaccard(a, b) == pytest.approx(0.5)


def test_jaccard_both_empty():
    assert _jaccard(frozenset(), frozenset()) == 1.0


# ---------------------------------------------------------------------------
# deduplicate
# ---------------------------------------------------------------------------

def test_dedup_unique_articles_pass_through():
    articles = [
        {"headline": "Fed cuts rates", "source": "Reuters"},
        {"headline": "Oil prices surge on OPEC cuts", "source": "AP"},
    ]
    result = deduplicate(articles, seen_headlines=[])
    assert len(result) == 2


def test_dedup_drops_db_match():
    articles = [{"headline": "Fed cuts rates unexpectedly", "source": "Reuters"}]
    seen = ["Fed cuts rates unexpectedly"]
    result = deduplicate(articles, seen_headlines=seen)
    assert len(result) == 0


def test_dedup_drops_in_batch_duplicate():
    articles = [
        {"headline": "Fed cuts rates unexpectedly", "source": "Reuters"},
        {"headline": "Fed cuts rates unexpectedly", "source": "Reuters"},
    ]
    result = deduplicate(articles, seen_headlines=[])
    assert len(result) == 1


def test_dedup_corroborates_different_source():
    articles = [
        {"headline": "Fed cuts rates unexpectedly", "source": "Reuters"},
        {"headline": "Fed cuts rates unexpectedly", "source": "AP"},
    ]
    result = deduplicate(articles, seen_headlines=[])
    assert len(result) == 1
    assert result[0]["source_count"] == 2


def test_dedup_same_source_duplicate_not_corroborated():
    articles = [
        {"headline": "Fed cuts rates unexpectedly", "source": "Reuters"},
        {"headline": "Fed cuts rates unexpectedly", "source": "Reuters"},
    ]
    result = deduplicate(articles, seen_headlines=[])
    assert len(result) == 1
    assert result[0]["source_count"] == 1


def test_dedup_empty_headline_passes_through():
    articles = [{"headline": "", "source": "Reuters"}]
    result = deduplicate(articles, seen_headlines=[])
    assert len(result) == 1
