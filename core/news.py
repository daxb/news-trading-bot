"""
Finnhub news wrapper for the Macro Trader bot.

Returns normalized dicts so the pipeline never depends on the
finnhub SDK's internal objects.
"""

import logging
from datetime import datetime, timezone

import finnhub
from finnhub.exceptions import FinnhubAPIException, FinnhubRequestException

from config import settings

logger = logging.getLogger(__name__)


def _normalize_article(raw: dict) -> dict:
    """Convert a raw Finnhub article dict into our standard schema."""
    return {
        "id": raw.get("id", 0),
        "headline": raw.get("headline", ""),
        "summary": raw.get("summary", ""),
        "source": raw.get("source", ""),
        "url": raw.get("url", ""),
        "category": raw.get("category", ""),
        "datetime": datetime.fromtimestamp(raw["datetime"], tz=timezone.utc).isoformat()
        if raw.get("datetime")
        else None,
        "related": raw.get("related", ""),
    }


class NewsClient:
    """Thin wrapper around the Finnhub news endpoints."""

    def __init__(self) -> None:
        if not settings.FINNHUB_API_KEY:
            raise ValueError("FINNHUB_API_KEY must be set in .env")

        self._client = finnhub.Client(api_key=settings.FINNHUB_API_KEY)
        logger.info("NewsClient initialized")

    # ------------------------------------------------------------------
    # General / market news
    # ------------------------------------------------------------------

    def get_general_news(
        self, category: str = "general", min_id: int = 0
    ) -> list[dict]:
        """
        Fetch general market news from Finnhub.

        Args:
            category: News category (general, forex, crypto, merger).
            min_id:   Only return articles with id > min_id (useful for polling).
        """
        try:
            raw_articles = self._client.general_news(category, min_id=min_id)
            articles = [_normalize_article(a) for a in raw_articles]
            logger.debug(
                "Fetched %d general news articles (category=%s)", len(articles), category
            )
            return articles
        except FinnhubAPIException as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                logger.warning(
                    "Finnhub rate limit hit (60 req/min) — skipping this poll cycle"
                )
            else:
                logger.warning("Finnhub API error (category=%s): %s", category, e)
            return []
        except FinnhubRequestException as e:
            logger.warning("Finnhub request failed (category=%s): %s", category, e)
            return []
        except Exception:
            logger.exception("Failed to fetch general news (category=%s)", category)
            return []

    def get_company_news(
        self, ticker: str, from_date: str, to_date: str
    ) -> list[dict]:
        """
        Fetch company-specific news.

        Args:
            ticker:    Stock symbol (e.g. 'AAPL').
            from_date: Start date as 'YYYY-MM-DD'.
            to_date:   End date as 'YYYY-MM-DD'.
        """
        try:
            raw_articles = self._client.company_news(
                ticker.upper(), _from=from_date, to=to_date
            )
            articles = [_normalize_article(a) for a in raw_articles]
            logger.debug(
                "Fetched %d articles for %s (%s to %s)",
                len(articles), ticker.upper(), from_date, to_date,
            )
            return articles
        except (FinnhubAPIException, FinnhubRequestException) as e:
            logger.warning("Finnhub error fetching company news for %s: %s", ticker.upper(), e)
            return []
        except Exception:
            logger.exception(
                "Failed to fetch company news for %s", ticker.upper()
            )
            return []

    def get_market_news(self, category: str = "general") -> list[dict]:
        """Alias for get_general_news (convenience method)."""
        return self.get_general_news(category=category)
