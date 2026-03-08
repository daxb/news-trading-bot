"""
Shared test fixtures and fakes for the FIONA test suite.

Provides reusable stubs (FakeBroker, FakeForexBroker, FakeMacroClient)
and an in-memory Database fixture so individual test files stay DRY.
"""

import pytest

from core.db import Database


# ---------------------------------------------------------------------------
# In-memory Database fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    """Fresh in-memory Database for each test."""
    database = Database(db_path=":memory:")
    yield database
    database.close()


# ---------------------------------------------------------------------------
# Fake broker stubs
# ---------------------------------------------------------------------------

class FakeBroker:
    """Stub implementing the BrokerClient duck-type interface."""

    def __init__(
        self,
        equity: float = 100_000.0,
        positions: list[dict] | None = None,
        prices: dict[str, float] | None = None,
        position_map: dict[str, dict] | None = None,
    ) -> None:
        self.equity = equity
        self.positions = positions or []
        self.prices = prices or {}
        self.position_map = position_map or {}
        self.submitted_orders: list[dict] = []
        self.closed_positions: list[str] = []

    def get_account(self) -> dict:
        return {"equity": self.equity, "cash": self.equity, "buying_power": self.equity}

    def get_positions(self) -> list[dict]:
        return self.positions

    def get_position(self, ticker: str) -> dict | None:
        return self.position_map.get(ticker)

    def get_latest_price(self, ticker: str) -> float | None:
        return self.prices.get(ticker)

    def submit_market_order(self, ticker: str, qty: float, side: str) -> dict:
        order = {"id": f"fake-{len(self.submitted_orders)}", "symbol": ticker, "qty": str(qty), "side": side, "status": "filled"}
        self.submitted_orders.append(order)
        return order

    def close_position(self, ticker: str) -> dict:
        self.closed_positions.append(ticker)
        return {"id": f"close-{ticker}", "status": "closed"}


class FakeForexBroker:
    """Stub implementing the ForexBroker duck-type interface."""

    def __init__(
        self,
        equity: float = 100_000.0,
        positions: list[dict] | None = None,
        prices: dict[str, float] | None = None,
        position_map: dict[str, dict] | None = None,
    ) -> None:
        self.equity = equity
        self.positions = positions or []
        self.prices = prices or {}
        self.position_map = position_map or {}
        self.closed_positions: list[str] = []

    def get_account(self) -> dict:
        return {"equity": self.equity}

    def get_positions(self) -> list[dict]:
        return self.positions

    def get_position(self, instrument: str) -> dict | None:
        return self.position_map.get(instrument)

    def get_latest_price(self, instrument: str) -> float | None:
        return self.prices.get(instrument)

    def close_position(self, instrument: str) -> dict:
        self.closed_positions.append(instrument)
        return {"id": f"close-{instrument}", "status": "closed"}


class FakeMacroClient:
    """Stub returning configurable indicator dicts."""

    def __init__(self, indicators: dict | None = None) -> None:
        self._indicators = indicators or {}

    def get_key_indicators(self) -> dict:
        return self._indicators


# ---------------------------------------------------------------------------
# Article / signal helpers
# ---------------------------------------------------------------------------

def make_article(article_id: int = 1, sentiment_label: str = "positive", headline: str = "Markets rally on strong jobs report") -> dict:
    return {
        "id": article_id,
        "headline": headline,
        "summary": "Stocks surged after better-than-expected data.",
        "source": "Reuters",
        "url": f"https://example.com/article/{article_id}",
        "category": "general",
        "datetime": "2026-03-04T12:00:00+00:00",
        "related": "SPY",
        "sentiment_label": sentiment_label,
        "sentiment_score": 0.92,
    }


def make_signal(article_id: int = 1, ticker: str = "SPY", action: str = "buy", confidence: float = 0.75) -> dict:
    return {
        "article_id": article_id,
        "ticker": ticker,
        "action": action,
        "confidence": confidence,
        "theme": "risk_on",
        "rationale": "Strong jobs → equities bullish",
    }
