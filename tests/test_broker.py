"""
Unit tests for core/broker.py — Alpaca broker wrapper.

All Alpaca SDK calls are mocked — no API keys or network required.

Run with:
    python -m pytest tests/test_broker.py -v
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from types import SimpleNamespace

from core.broker import BrokerClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_broker():
    """Construct a BrokerClient bypassing __init__."""
    broker = BrokerClient.__new__(BrokerClient)
    broker._client = MagicMock()
    broker._data_client = MagicMock()
    broker._last_error = ""
    return broker


# ---------------------------------------------------------------------------
# get_account
# ---------------------------------------------------------------------------

def test_get_account_returns_dict():
    broker = _make_broker()
    mock_acct = SimpleNamespace(
        id="abc", status="ACTIVE", cash=50000.0, buying_power=100000.0,
        portfolio_value=100000.0, equity=100000.0, last_equity=99000.0,
        created_at="2026-01-01", currency="USD", pattern_day_trader=False,
    )
    broker._client.get_account.return_value = mock_acct
    result = broker.get_account()
    assert result["equity"] == 100000.0
    assert result["cash"] == 50000.0
    assert result["currency"] == "USD"


def test_get_account_exception_returns_empty():
    broker = _make_broker()
    broker._client.get_account.side_effect = RuntimeError("fail")
    result = broker.get_account()
    assert result == {}


# ---------------------------------------------------------------------------
# get_positions
# ---------------------------------------------------------------------------

def test_get_positions_returns_list():
    broker = _make_broker()
    mock_pos = SimpleNamespace(
        symbol="SPY", qty=10.0, side="long", market_value=5000.0,
        avg_entry_price=490.0, current_price=500.0,
        unrealized_pl=100.0, unrealized_plpc=0.02,
    )
    broker._client.get_all_positions.return_value = [mock_pos]
    result = broker.get_positions()
    assert len(result) == 1
    assert result[0]["symbol"] == "SPY"
    assert result[0]["qty"] == 10.0


# ---------------------------------------------------------------------------
# submit_market_order
# ---------------------------------------------------------------------------

def test_submit_market_order_buy():
    broker = _make_broker()
    mock_order = SimpleNamespace(
        id="order-1", symbol="SPY", qty=5.0, side="buy",
        type="market", status="accepted", submitted_at="2026-01-01",
    )
    broker._client.submit_order.return_value = mock_order
    result = broker.submit_market_order("SPY", 5.0, "buy")
    assert result["side"] == "buy"
    assert result["symbol"] == "SPY"


def test_submit_market_order_sell():
    broker = _make_broker()
    mock_order = SimpleNamespace(
        id="order-2", symbol="SPY", qty=5.0, side="sell",
        type="market", status="accepted", submitted_at="2026-01-01",
    )
    broker._client.submit_order.return_value = mock_order
    result = broker.submit_market_order("SPY", 5.0, "sell")
    assert result["side"] == "sell"


def test_submit_market_order_failure_returns_falsy_and_sets_last_error():
    """On failure the order must be FALSY (not a truthy error dict) so the
    scheduler's `if order:` correctly treats it as a non-execution, and the
    specific reason must be retrievable via get_last_error().

    Regression: previously returned {"error": ...} (truthy), which the scheduler
    read as a successful execution and recorded as a phantom 'executed' signal.
    """
    broker = _make_broker()
    broker._client.submit_order.side_effect = RuntimeError("insufficient buying power")
    result = broker.submit_market_order("SPY", 5.0, "buy")
    assert not result, f"failed order must be falsy, got truthy: {result!r}"
    assert "insufficient buying power" in broker.get_last_error()


def test_submit_market_order_success_clears_last_error():
    """A successful submit must leave get_last_error() empty so a stale error
    from a prior failed call never leaks into the next signal's skip_reason."""
    broker = _make_broker()
    broker._last_error = "stale error from previous call"
    mock_order = SimpleNamespace(
        id="order-3", symbol="SPY", qty=5.0, side="buy",
        type="market", status="accepted", submitted_at="2026-01-01",
    )
    broker._client.submit_order.return_value = mock_order
    result = broker.submit_market_order("SPY", 5.0, "buy")
    assert result  # truthy on success
    assert broker.get_last_error() == ""


def test_submit_market_order_includes_filled_avg_price():
    """Success path must include the real fill price from the order."""
    broker = _make_broker()
    mock_order = SimpleNamespace(
        id="order-3", symbol="SPY", qty=5.0, side="buy",
        type="market", status="filled", submitted_at="2026-01-01",
        filled_avg_price=755.18,
    )
    broker._client.submit_order.return_value = mock_order
    result = broker.submit_market_order("SPY", 5.0, "buy")
    assert result["filled_avg_price"] == 755.18


def test_submit_market_order_filled_avg_price_none():
    """When the order has no fill price yet, filled_avg_price must be None."""
    broker = _make_broker()
    mock_order = SimpleNamespace(
        id="order-4", symbol="SPY", qty=5.0, side="buy",
        type="market", status="accepted", submitted_at="2026-01-01",
        filled_avg_price=None,
    )
    broker._client.submit_order.return_value = mock_order
    result = broker.submit_market_order("SPY", 5.0, "buy")
    assert result["filled_avg_price"] is None


# ---------------------------------------------------------------------------
# get_order
# ---------------------------------------------------------------------------

def test_get_order_returns_status_and_fill():
    broker = _make_broker()
    mock_order = SimpleNamespace(status="filled", filled_avg_price=755.18)
    broker._client.get_order_by_id.return_value = mock_order
    result = broker.get_order("order-1")
    assert result == {"status": "filled", "filled_avg_price": 755.18}


def test_get_order_no_fill_price():
    broker = _make_broker()
    mock_order = SimpleNamespace(status="accepted", filled_avg_price=None)
    broker._client.get_order_by_id.return_value = mock_order
    result = broker.get_order("order-2")
    assert result["status"] == "accepted"
    assert result["filled_avg_price"] is None


def test_get_order_exception_returns_none():
    broker = _make_broker()
    broker._client.get_order_by_id.side_effect = RuntimeError("boom")
    result = broker.get_order("order-x")
    assert result is None


# ---------------------------------------------------------------------------
# get_position
# ---------------------------------------------------------------------------

def test_get_position_found():
    broker = _make_broker()
    mock_pos = SimpleNamespace(symbol="SPY", qty=10.0, side="long", market_value=5000.0)
    broker._client.get_open_position.return_value = mock_pos
    result = broker.get_position("SPY")
    assert result is not None
    assert result["symbol"] == "SPY"


def test_get_position_not_found():
    broker = _make_broker()
    broker._client.get_open_position.side_effect = Exception("404")
    result = broker.get_position("AAPL")
    assert result is None


# ---------------------------------------------------------------------------
# close_position
# ---------------------------------------------------------------------------

def test_close_position():
    broker = _make_broker()
    mock_order = SimpleNamespace(id="close-1", status="filled")
    broker._client.close_position.return_value = mock_order
    result = broker.close_position("SPY")
    assert result["id"] == "close-1"
    assert result["status"] == "filled"
