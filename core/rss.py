"""
RSS news client for the Macro Trader bot.

Fetches articles from free financial/macro RSS feeds and normalises them
to the same schema used by core/news.py so the rest of the pipeline is
source-agnostic.

Article IDs
-----------
RSS entries have no numeric ID. We use zlib.crc32(url) to produce a
stable 32-bit integer — small enough to coexist with Finnhub's IDs in
the same SQLite column without collision risk.
"""

import logging
import zlib
from calendar import timegm
from datetime import datetime, timezone
from time import struct_time

import feedparser

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Feed registry — add or remove feeds here without touching any other file
# ---------------------------------------------------------------------------
_FEEDS: list[dict] = [
    {
        "name": "BBC World",
        "url": "http://feeds.bbci.co.uk/news/world/rss.xml",
    },
    {
        "name": "BBC Business",
        "url": "http://feeds.bbci.co.uk/news/business/rss.xml",
    },
    {
        "name": "CNBC Top News",
        "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    },
    {
        "name": "MarketWatch",
        "url": "https://feeds.marketwatch.com/marketwatch/topstories/",
    },
    {
        "name": "Yahoo Finance",
        "url": "https://finance.yahoo.com/news/rssindex",
    },
]


def _stable_id(url: str) -> int:
    """Return a stable positive integer ID derived from the article URL."""
    return zlib.crc32(url.encode()) & 0x7FFF_FFFF


def _parse_datetime(published: struct_time | None) -> str | None:
    """Convert a feedparser time.struct_time to a UTC ISO-8601 string."""
    if not published:
        return None
    ts = timegm(published)  # treats struct_time as UTC
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _normalize_entry(entry: feedparser.FeedParserDict, source: str) -> dict:
    """Convert a feedparser entry to our standard article schema."""
    url = entry.get("link", "")
    summary = entry.get("summary", "") or entry.get("description", "")
    # Strip HTML tags that some feeds include in summaries
    if "<" in summary:
        import re
        summary = re.sub(r"<[^>]+>", "", summary).strip()

    return {
        "id": _stable_id(url) if url else 0,
        "headline": entry.get("title", "").strip(),
        "summary": summary,
        "source": source,
        "url": url,
        "category": "rss",
        "datetime": _parse_datetime(entry.get("published_parsed")),
        "related": "",
    }


class RSSClient:
    """Fetches and normalises articles from all configured RSS feeds."""

    def get_articles(self) -> list[dict]:
        """
        Fetch all configured feeds and return a flat list of normalised articles.

        Feeds that fail to load are skipped with a warning — one bad feed
        should never block the rest.
        """
        all_articles: list[dict] = []

        for feed in _FEEDS:
            name = feed["name"]
            url = feed["url"]
            try:
                parsed = feedparser.parse(url)
                if parsed.bozo and not parsed.entries:
                    logger.warning(
                        "RSS feed '%s' returned a parse error and no entries — skipping",
                        name,
                    )
                    continue

                articles = [
                    _normalize_entry(e, name)
                    for e in parsed.entries
                    if e.get("link")  # skip entries with no URL (no stable ID)
                ]
                logger.debug("RSS '%s': fetched %d articles", name, len(articles))
                all_articles.extend(articles)

            except Exception:
                logger.exception("Failed to fetch RSS feed '%s'", name)

        logger.info("RSS total: fetched %d articles from %d feeds", len(all_articles), len(_FEEDS))
        return all_articles
