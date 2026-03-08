"""
Unit tests for core/forex.py — OANDA broker wrapper.

All OANDA SDK calls are mocked — no API keys or network required.

Run with:
    python -m pytest tests/test_forex.py -v
"""

import pytest
from unittest.mock import MagicMock

oandapyV20 = pytest.importorskip("oandapyV20", reason="oandapyV20 not installed")
from core.forex import ForexBroker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_forex():
    """Construct a ForexBroker bypassing __init__."""
    fx = ForexBroker.__new__(ForexBroker)
    fx._account_id = "test-account"
    fx._client = MagicMock()
    return fx


# ---------------------------------------------------------------------------
# get_account
# ---------------------------------------------------------------------------

def test_get_account_returns_dict():
    fx = _make_forex()

    def fake_request(r):
        r.response = {"account": {
            "NAV": "100000.00", "balance": "95000.00",
            "marginAvailable": "80000.00", "currency": "USD",
        }}

    fx._client.request = fake_request
    result = fx.get_account()
    assert result["equity"] == 100000.0
    assert result["cash"] == 95000.0


def test_get_account_exception_returns_empty():
    fx = _make_forex()
    fx._client.request = MagicMock(side_effect=RuntimeError("fail"))
    result = fx.get_account()
    assert result == {}


# ---------------------------------------------------------------------------
# get_latest_price
# ---------------------------------------------------------------------------

def test_get_latest_price_mid_calculation():
    fx = _make_forex()

    def fake_request(r):
        r.response = {"prices": [{
            "bids": [{"price": "1.10000"}],
            "asks": [{"price": "1.10020"}],
        }]}

    fx._client.request = fake_request
    result = fx.get_latest_price("EUR_USD")
    assert result == pytest.approx(1.10010, abs=0.00001)


# ---------------------------------------------------------------------------
# get_position
# ---------------------------------------------------------------------------

def test_get_position_long():
    fx = _make_forex()

    def fake_request(r):
        r.response = {"position": {
            "long": {"units": "100"},
            "short": {"units": "0"},
        }}

    fx._client.request = fake_request
    result = fx.get_position("EUR_USD")
    assert result is not None
    assert result["side"] == "long"
    assert result["units"] == 100


def test_get_position_short():
    fx = _make_forex()

    def fake_request(r):
        r.response = {"position": {
            "long": {"units": "0"},
            "short": {"units": "-50"},
        }}

    fx._client.request = fake_request
    result = fx.get_position("EUR_USD")
    assert result is not None
    assert result["side"] == "short"
    assert result["units"] == -50


def test_get_position_flat():
    fx = _make_forex()

    def fake_request(r):
        r.response = {"position": {
            "long": {"units": "0"},
            "short": {"units": "0"},
        }}

    fx._client.request = fake_request
    result = fx.get_position("EUR_USD")
    assert result is None


def test_get_position_no_position_error():
    fx = _make_forex()
    from oandapyV20.exceptions import V20Error
    fx._client.request = MagicMock(side_effect=V20Error(404, "No position"))
    result = fx.get_position("EUR_USD")
    assert result is None


# ---------------------------------------------------------------------------
# submit_market_order
# ---------------------------------------------------------------------------

def test_submit_market_order_buy_positive_units():
    fx = _make_forex()

    def fake_request(r):
        r.response = {"orderFillTransaction": {
            "id": "123", "instrument": "EUR_USD", "units": "100", "price": "1.10",
        }}

    fx._client.request = fake_request
    result = fx.submit_market_order("EUR_USD", 100.0, "buy")
    assert result["units"] == "100"
    assert result["status"] == "filled"


def test_submit_market_order_sell_negative_units():
    fx = _make_forex()

    def fake_request(r):
        r.response = {"orderFillTransaction": {
            "id": "124", "instrument": "EUR_USD", "units": "-100", "price": "1.10",
        }}

    fx._client.request = fake_request
    result = fx.submit_market_order("EUR_USD", 100.0, "sell")
    assert result["status"] == "filled"


def test_submit_market_order_zero_qty_aborts():
    fx = _make_forex()
    result = fx.submit_market_order("EUR_USD", 0.4, "buy")
    assert result == {}
