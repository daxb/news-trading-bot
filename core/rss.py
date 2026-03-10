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
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from datetime import datetime, timezone
from time import struct_time

import feedparser

from config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Feed registry — add or remove feeds here without touching any other file
# ---------------------------------------------------------------------------
_FEEDS: list[dict] = [
    {
        "name": "Sky News World",
        "url": "https://feeds.skynews.com/feeds/rss/world.xml",
    },
    {
        "name": "Sky News Business",
        "url": "https://feeds.skynews.com/feeds/rss/business.xml",
    },
    {
        "name": "CNBC Top News",
        "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    },
    {
        "name": "NPR News",
        "url": "https://feeds.npr.org/1001/rss.xml",
    },
    {
        "name": "The Guardian World",
        "url": "https://www.theguardian.com/world/rss",
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

    def _fetch_feed(self, feed: dict) -> list[dict]:
        """Fetch and normalise a single feed. Runs in a thread pool worker."""
        name = feed["name"]
        url  = feed["url"]
        parsed = feedparser.parse(url)

        http_status = parsed.get("status")
        if http_status and http_status not in (200, 301, 302):
            logger.warning("RSS feed '%s' HTTP %d — skipping", name, http_status)
            return []

        if parsed.bozo and not parsed.entries:
            if parsed.bozo_exception:
                logger.warning(
                    "RSS feed '%s' parse error: %s — skipping",
                    name, parsed.bozo_exception,
                )
            else:
                logger.warning("RSS feed '%s' parse error — skipping", name)
            return []

        articles = [
            _normalize_entry(e, name)
            for e in parsed.entries
            if e.get("link")
        ]
        logger.info("RSS '%s': fetched %d articles", name, len(articles))
        return articles

    def get_articles(self) -> list[dict]:
        """
        Fetch all configured feeds concurrently and return a flat list.

        Each feed runs in its own thread. Feeds that time out or error are
        skipped — one bad feed never delays the rest.
        """
        all_articles: list[dict] = []
        timeout = settings.NEWS_FETCH_TIMEOUT_SECONDS

        with ThreadPoolExecutor(max_workers=len(_FEEDS)) as executor:
            future_to_feed = {
                executor.submit(self._fetch_feed, feed): feed
                for feed in _FEEDS
            }
            for future in as_completed(future_to_feed, timeout=timeout * 2):
                feed = future_to_feed[future]
                try:
                    articles = future.result(timeout=timeout)
                    all_articles.extend(articles)
                except TimeoutError:
                    logger.warning("RSS feed '%s' timed out after %ds", feed["name"], timeout)
                except Exception:
                    logger.exception("RSS feed '%s' failed", feed["name"])

        logger.info("RSS total: fetched %d articles from %d feeds", len(all_articles), len(_FEEDS))
        return all_articles
