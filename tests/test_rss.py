"""
Unit tests for core/rss.py — RSS feed fetcher and normaliser.

Internal functions are tested directly. feedparser is monkeypatched
for get_articles tests.

Run with:
    python -m pytest tests/test_rss.py -v
"""

import pytest
from time import struct_time

feedparser = pytest.importorskip("feedparser", reason="feedparser not installed")
from core.rss import _stable_id, _parse_datetime, _normalize_entry


# ---------------------------------------------------------------------------
# _stable_id
# ---------------------------------------------------------------------------

def test_stable_id_deterministic():
    url = "https://example.com/article/123"
    assert _stable_id(url) == _stable_id(url)


def test_stable_id_positive():
    url = "https://example.com/article/negative-test"
    assert _stable_id(url) > 0


def test_stable_id_different_urls():
    assert _stable_id("https://a.com") != _stable_id("https://b.com")


# ---------------------------------------------------------------------------
# _parse_datetime
# ---------------------------------------------------------------------------

def test_parse_datetime_valid():
    # 2026-01-15 12:00:00 UTC as struct_time
    st = struct_time((2026, 1, 15, 12, 0, 0, 3, 15, 0))
    result = _parse_datetime(st)
    assert result is not None
    assert "2026-01-15" in result
    assert "12:00:00" in result


def test_parse_datetime_none():
    assert _parse_datetime(None) is None


# ---------------------------------------------------------------------------
# _normalize_entry
# ---------------------------------------------------------------------------

def test_normalize_entry_strips_html():
    entry = {
        "title": "Test Article",
        "link": "https://example.com/1",
        "summary": "<b>Bold</b> text with <a href='#'>link</a>",
    }
    result = _normalize_entry(entry, "TestSource")
    assert "<" not in result["summary"]
    assert "Bold" in result["summary"]


def test_normalize_entry_schema():
    entry = {
        "title": "Test Article",
        "link": "https://example.com/1",
        "summary": "A summary",
        "published_parsed": None,
    }
    result = _normalize_entry(entry, "TestSource")
    expected_keys = {"id", "headline", "summary", "source", "url", "category", "datetime", "related"}
    assert set(result.keys()) == expected_keys
    assert result["source"] == "TestSource"
    assert result["category"] == "rss"


def test_normalize_entry_no_link():
    entry = {"title": "No link article", "summary": "text"}
    result = _normalize_entry(entry, "Source")
    assert result["id"] == 0
    assert result["url"] == ""
