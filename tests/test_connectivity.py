"""
Phase 0 integration smoke tests — hit the real APIs and verify
basic connectivity and schema compliance.

Run with:
    python -m pytest tests/test_connectivity.py -v -m integration
"""

import pytest
from datetime import date, timedelta


# ---------------------------------------------------------------------------
# Finnhub / NewsClient tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_finnhub_general_news():
    """
    get_market_news() must return a non-empty list and every item must
    have 'headline' and 'datetime' keys.
    
    Rationale: if the list is empty or keys are missing, either the API
    key is broken, the feed is down, or _normalize_article changed schema.
    """
    from core.news import NewsClient

    client = NewsClient()
    articles = client.get_market_news()

    assert isinstance(articles, list), "Expected a list, got %s" % type(articles)
    assert len(articles) > 0, (
        "get_market_news() returned an empty list — "
        "API key invalid, rate-limited, or feed is down"
    )

    for article in articles:
        assert "headline" in article, (
            "Article missing 'headline' key. Keys present: %s" % list(article.keys())
        )
        assert "datetime" in article, (
            "Article missing 'datetime' key. Keys present: %s" % list(article.keys())
        )


@pytest.mark.integration
def test_finnhub_company_news():
    """
    get_company_news() for AAPL over the last 7 days must return a list
    without raising. Empty is acceptable (e.g. weekend/holiday window),
    but an exception would indicate a wrapper or API key problem.

    The wrapper swallows exceptions and returns [] — so we verify the
    return type and, when results exist, validate the schema.
    """
    from core.news import NewsClient

    client = NewsClient()
    to_date = date.today().strftime("%Y-%m-%d")
    from_date = (date.today() - timedelta(days=7)).strftime("%Y-%m-%d")

    articles = client.get_company_news("AAPL", from_date, to_date)

    assert isinstance(articles, list), (
        "get_company_news() must return a list, got %s" % type(articles)
    )

    # If we did get articles, validate their schema
    for article in articles:
        assert "headline" in article, (
            "Company news article missing 'headline'. Keys: %s" % list(article.keys())
        )
        assert "datetime" in article, (
            "Company news article missing 'datetime'. Keys: %s" % list(article.keys())
        )


# ---------------------------------------------------------------------------
# FRED / MacroClient tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_fred_key_indicators():
    """
    get_key_indicators() must return a dict that contains at minimum
    FEDFUNDS and CPIAUCSL, and each must have a numeric 'value'.

    These two series are always published — missing them means the FRED
    API key is broken or the wrapper has a schema bug.
    """
    from core.macro import MacroClient

    client = MacroClient()
    indicators = client.get_key_indicators()

    assert isinstance(indicators, dict), (
        "get_key_indicators() must return a dict, got %s" % type(indicators)
    )

    for required_series in ("FEDFUNDS", "CPIAUCSL"):
        assert required_series in indicators, (
            "Expected '%s' in key indicators. Got keys: %s"
            % (required_series, list(indicators.keys()))
        )
        entry = indicators[required_series]
        assert "value" in entry, (
            "%s entry missing 'value' key. Got: %s" % (required_series, entry)
        )
        assert isinstance(entry["value"], (int, float)), (
            "%s 'value' must be numeric, got %s (%s)"
            % (required_series, entry["value"], type(entry["value"]))
        )


@pytest.mark.integration
def test_fred_series():
    """
    get_series('FEDFUNDS', limit=5) must return exactly 5 dicts,
    each containing 'date' (a string) and 'value' (a float).

    FEDFUNDS has data back to 1954 — there will always be >= 5 observations.
    """
    from core.macro import MacroClient

    client = MacroClient()
    observations = client.get_series("FEDFUNDS", limit=5)

    assert isinstance(observations, list), (
        "get_series() must return a list, got %s" % type(observations)
    )
    assert len(observations) == 5, (
        "Expected 5 observations, got %d. "
        "FEDFUNDS has decades of data — this should never be short."
        % len(observations)
    )

    for obs in observations:
        assert "date" in obs, (
            "Observation missing 'date' key. Got: %s" % obs
        )
        assert "value" in obs, (
            "Observation missing 'value' key. Got: %s" % obs
        )
        assert isinstance(obs["date"], str), (
            "'date' must be a string, got %s" % type(obs["date"])
        )
        assert isinstance(obs["value"], float), (
            "'value' must be a float, got %s (%s)" % (obs["value"], type(obs["value"]))
        )


# ---------------------------------------------------------------------------
# Alpaca / BrokerClient tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_alpaca_account():
    """
    get_account() must return a dict with 'portfolio_value' and
    'buying_power', both numeric.

    BrokerClient.get_account() silently returns {} on any exception,
    so asserting specific keys is the only way to catch silent failures.
    """
    from core.broker import BrokerClient

    client = BrokerClient()
    account = client.get_account()

    assert isinstance(account, dict), (
        "get_account() must return a dict, got %s" % type(account)
    )
    assert account, (
        "get_account() returned an empty dict — API auth failure or network error. "
        "Check ALPACA_API_KEY / ALPACA_SECRET_KEY in .env"
    )

    for key in ("portfolio_value", "buying_power"):
        assert key in account, (
            "Account dict missing '%s'. Got keys: %s" % (key, list(account.keys()))
        )
        assert isinstance(account[key], (int, float)), (
            "'%s' must be numeric, got %s (%s)"
            % (key, account[key], type(account[key]))
        )


@pytest.mark.integration
def test_alpaca_positions():
    """
    get_positions() must return a list without raising.
    Empty is fine for a paper account with no open trades.
    """
    from core.broker import BrokerClient

    client = BrokerClient()
    positions = client.get_positions()

    assert isinstance(positions, list), (
        "get_positions() must return a list, got %s" % type(positions)
    )

    # If there are positions, validate their schema
    for pos in positions:
        for key in ("symbol", "qty", "side", "market_value"):
            assert key in pos, (
                "Position missing '%s' key. Got: %s" % (key, list(pos.keys()))
            )


# ---------------------------------------------------------------------------
# Settings tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_paper_mode_is_default():
    """
    PAPER_TRADING must default to True unless explicitly set to 'false'.
    This is a safety gate — if it flips to False accidentally, real money
    gets traded.
    """
    from config.settings import PAPER_TRADING

    assert PAPER_TRADING is True, (
        "PAPER_TRADING is not True! Current value: %s. "
        "This means live trading may be active. Check .env immediately."
        % PAPER_TRADING
    )
