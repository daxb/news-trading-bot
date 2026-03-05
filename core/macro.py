"""
FRED macro-economic data wrapper for the Macro Trader bot.

Uses the fredapi package and returns plain dicts/lists so the
pipeline is decoupled from pandas internals.
"""

import logging
from typing import Optional

from fredapi import Fred

from config import settings

logger = logging.getLogger(__name__)

# Key macro series we track, with human-readable labels
KEY_INDICATORS = {
    "FEDFUNDS": "Fed Funds Rate",
    "CPIAUCSL": "CPI (Inflation)",
    "UNRATE": "Unemployment Rate",
    "GDP": "GDP",
    "DGS10": "10-Year Treasury Yield",
}


class MacroClient:
    """Thin wrapper around FRED API for macro-economic data."""

    def __init__(self) -> None:
        if not settings.FRED_API_KEY:
            raise ValueError("FRED_API_KEY must be set in .env")

        self._fred = Fred(api_key=settings.FRED_API_KEY)
        logger.info("MacroClient initialized")

    # ------------------------------------------------------------------
    # Series data
    # ------------------------------------------------------------------

    def get_series(self, series_id: str, limit: int = 10) -> list[dict]:
        """
        Fetch the last `limit` observations for a FRED series.

        Returns a list of dicts: [{"date": "YYYY-MM-DD", "value": float}, ...]
        NaN values are excluded.
        """
        try:
            data = self._fred.get_series(series_id)
            # data is a pandas Series indexed by date
            data = data.dropna().tail(limit)
            result = [
                {
                    "date": date.strftime("%Y-%m-%d"),
                    "value": float(value),
                }
                for date, value in data.items()
            ]
            logger.debug(
                "Fetched %d observations for %s", len(result), series_id
            )
            return result
        except Exception:
            logger.exception("Failed to fetch series %s", series_id)
            return []

    # ------------------------------------------------------------------
    # Key indicators snapshot
    # ------------------------------------------------------------------

    def get_key_indicators(self) -> dict:
        """
        Fetch the latest value for each key macro indicator.

        Returns a dict like:
        {
            "FEDFUNDS": {"label": "Fed Funds Rate", "date": "2024-01-01", "value": 5.33},
            "CPIAUCSL": {"label": "CPI (Inflation)", "date": "...", "value": ...},
            ...
        }
        Series that fail to load are omitted with a warning.
        """
        indicators: dict = {}

        for series_id, label in KEY_INDICATORS.items():
            observations = self.get_series(series_id, limit=1)
            if observations:
                latest = observations[-1]
                indicators[series_id] = {
                    "label": label,
                    "date": latest["date"],
                    "value": latest["value"],
                }
            else:
                logger.warning(
                    "Could not fetch indicator %s (%s)", series_id, label
                )

        logger.info(
            "Fetched %d / %d key indicators",
            len(indicators), len(KEY_INDICATORS),
        )
        return indicators
