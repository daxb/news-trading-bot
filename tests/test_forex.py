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

def _make_forex(tradeable_instruments=None):
    """Construct a ForexBroker bypassing __init__.

    tradeable_instruments: set of instrument names treated as enabled for the
    account. None (default) = empty set, which fail-opens so legacy tests
    that don't care about the account check still pass.
    """
    fx = ForexBroker.__new__(ForexBroker)
    fx._account_id = "test-account"
    fx._client = MagicMock()
    fx._last_error = ""
    fx._tradeable_instruments = set(tradeable_instruments or [])
    return fx


def _multi_response(responses_by_class: dict):
    """fake_request that dispatches on the request endpoint class name.

    Used to handle submit_market_order's two-step flow (PricingInfo for the
    tradeable check, then OrderCreate for the order itself).
    """
    def fake_request(r):
        cls_name = type(r).__name__
        if cls_name not in responses_by_class:
            raise AssertionError(
                f"Unexpected OANDA request in test: {cls_name} — "
                f"add it to the responses_by_class dict"
            )
        r.response = responses_by_class[cls_name]
    return fake_request


_TRADEABLE_PRICE_RESPONSE = {
    "prices": [{
        "tradeable": True,
        "bids": [{"price": "1.10000"}],
        "asks": [{"price": "1.10020"}],
    }]
}


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
    fx._client.request = _multi_response({
        "PricingInfo": _TRADEABLE_PRICE_RESPONSE,
        "OrderCreate": {"orderFillTransaction": {
            "id": "123", "instrument": "EUR_USD", "units": "100", "price": "1.10",
        }},
    })
    result = fx.submit_market_order("EUR_USD", 100.0, "buy")
    assert result["units"] == "100"
    assert result["status"] == "filled"
    assert fx.get_last_error() == ""


def test_submit_market_order_sell_negative_units():
    fx = _make_forex()
    fx._client.request = _multi_response({
        "PricingInfo": _TRADEABLE_PRICE_RESPONSE,
        "OrderCreate": {"orderFillTransaction": {
            "id": "124", "instrument": "EUR_USD", "units": "-100", "price": "1.10",
        }},
    })
    result = fx.submit_market_order("EUR_USD", 100.0, "sell")
    assert result["status"] == "filled"


def test_submit_market_order_zero_qty_aborts():
    fx = _make_forex()
    result = fx.submit_market_order("EUR_USD", 0.4, "buy")
    assert result == {}
    assert fx.get_last_error() == "rounded_units_zero"


# ---------------------------------------------------------------------------
# Account-level tradeability pre-flight
# ---------------------------------------------------------------------------

def test_submit_market_order_skips_when_instrument_not_in_account():
    """If the instrument isn't in the cached tradeable set, skip with clear error."""
    fx = _make_forex(tradeable_instruments={"EUR_USD", "GBP_USD"})
    result = fx.submit_market_order("BCO_USD", 44.0, "buy")
    assert result == {}
    assert fx.get_last_error() == "instrument_not_enabled_for_account"


def test_account_check_fails_open_with_empty_cache():
    """Empty tradeable set = couldn't load it; all instruments pass the pre-flight."""
    fx = _make_forex(tradeable_instruments=None)
    fx._client.request = _multi_response({
        "PricingInfo": _TRADEABLE_PRICE_RESPONSE,
        "OrderCreate": {"orderFillTransaction": {
            "id": "999", "instrument": "BCO_USD", "units": "44", "price": "80.0",
        }},
    })
    result = fx.submit_market_order("BCO_USD", 44.0, "buy")
    assert result["status"] == "filled", "Fail-open should let the order through to OANDA"


def test_is_account_tradeable():
    fx = _make_forex(tradeable_instruments={"EUR_USD", "XAU_USD"})
    assert fx.is_account_tradeable("EUR_USD") is True
    assert fx.is_account_tradeable("eur_usd") is True  # case insensitive
    assert fx.is_account_tradeable("BCO_USD") is False


# ---------------------------------------------------------------------------
# V20 error capture
# ---------------------------------------------------------------------------

def test_submit_market_order_captures_v20_error_code():
    """V20Error response is parsed and errorCode persisted to _last_error."""
    from oandapyV20.exceptions import V20Error
    fx = _make_forex(tradeable_instruments={"BCO_USD"})

    def fake_request(r):
        if type(r).__name__ == "PricingInfo":
            r.response = _TRADEABLE_PRICE_RESPONSE
            return
        # OrderCreate raises a V20Error with a real OANDA-shaped body
        body = (
            '{"orderRejectTransaction":{"id":"2067","rejectReason":"INSTRUMENT_NOT_TRADEABLE",'
            '"instrument":"BCO_USD"},"errorMessage":"The instrument specified is not tradeable",'
            '"errorCode":"INSTRUMENT_NOT_TRADEABLE"}'
        )
        raise V20Error(400, body)

    fx._client.request = fake_request
    result = fx.submit_market_order("BCO_USD", 44.0, "buy")
    assert result == {}
    assert fx.get_last_error() == "v20_error:INSTRUMENT_NOT_TRADEABLE"


def test_submit_market_order_captures_reject_transaction_inline():
    """Some OANDA responses return rejectReason in body without raising."""
    fx = _make_forex(tradeable_instruments={"EUR_USD"})
    fx._client.request = _multi_response({
        "PricingInfo": _TRADEABLE_PRICE_RESPONSE,
        "OrderCreate": {"orderRejectTransaction": {
            "id": "2068",
            "rejectReason": "MARKET_HALTED",
            "instrument": "EUR_USD",
        }},
    })
    result = fx.submit_market_order("EUR_USD", 100.0, "buy")
    assert result == {}
    assert fx.get_last_error() == "order_rejected:MARKET_HALTED"


def test_market_closed_captured_as_skip_reason():
    """If pricing returns tradeable=False, last_error reports market_closed."""
    fx = _make_forex(tradeable_instruments={"EUR_USD"})
    fx._client.request = _multi_response({
        "PricingInfo": {"prices": [{"tradeable": False,
                                     "bids": [{"price": "1.10"}],
                                     "asks": [{"price": "1.10"}]}]},
    })
    result = fx.submit_market_order("EUR_USD", 100.0, "buy")
    assert result == {}
    assert fx.get_last_error() == "market_closed"


# ---------------------------------------------------------------------------
# _extract_v20_error_code pure function
# ---------------------------------------------------------------------------

def test_extract_v20_error_code_from_top_level():
    from core.forex import _extract_v20_error_code
    body = '{"errorCode":"INSTRUMENT_NOT_TRADEABLE","errorMessage":"..."}'
    assert _extract_v20_error_code(body) == "INSTRUMENT_NOT_TRADEABLE"


def test_extract_v20_error_code_from_reject_transaction():
    from core.forex import _extract_v20_error_code
    body = '{"orderRejectTransaction":{"rejectReason":"INSUFFICIENT_MARGIN"}}'
    assert _extract_v20_error_code(body) == "INSUFFICIENT_MARGIN"


def test_extract_v20_error_code_handles_bad_json():
    from core.forex import _extract_v20_error_code
    assert _extract_v20_error_code("not json at all") == ""
    assert _extract_v20_error_code("") == ""
    assert _extract_v20_error_code("[1,2,3]") == ""  # list, not dict
