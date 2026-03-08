"""
Unit tests for core/exit_manager.py — trailing stops and time-based exits.

All external collaborators replaced with FakeBroker + in-memory DB.
No API keys, no network, no ML models required.

Run with:
    python -m pytest tests/test_exit_manager.py -v
"""

import pytest
from datetime import datetime, timedelta, timezone

from tests.conftest import FakeBroker, FakeForexBroker, make_article, make_signal

from config import settings
from core.exit_manager import ExitManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_exit_manager(broker=None, db=None, forex=None):
    em = ExitManager.__new__(ExitManager)
    em._broker = broker or FakeBroker()
    em._forex = forex
    em._db = db
    em._peak_prices = {}
    return em


def _insert_executed_signal(db, ticker="SPY", hours_ago=0):
    """Insert an article + executed signal with a known executed_at timestamp."""
    art_id = abs(hash(f"{ticker}{hours_ago}")) % 1_000_000
    db.save_article(make_article(article_id=art_id))
    sig_id = db.save_signal(make_signal(article_id=art_id, ticker=ticker))
    executed_at = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    db.update_signal_status(sig_id, "executed", executed_at=executed_at)
    return sig_id


# ---------------------------------------------------------------------------
# _update_peak
# ---------------------------------------------------------------------------

def test_update_peak_initial_price(db):
    em = _make_exit_manager(db=db)
    em._update_peak("SPY", "long", 100.0)
    assert em._peak_prices["SPY"] == 100.0


def test_update_peak_long_higher_price(db):
    em = _make_exit_manager(db=db)
    em._peak_prices["SPY"] = 100.0
    em._update_peak("SPY", "long", 110.0)
    assert em._peak_prices["SPY"] == 110.0


def test_update_peak_long_lower_price(db):
    em = _make_exit_manager(db=db)
    em._peak_prices["SPY"] = 100.0
    em._update_peak("SPY", "long", 90.0)
    assert em._peak_prices["SPY"] == 100.0


def test_update_peak_short_lower_price(db):
    em = _make_exit_manager(db=db)
    em._peak_prices["EUR_USD"] = 1.1000
    em._update_peak("EUR_USD", "short", 1.0900)
    assert em._peak_prices["EUR_USD"] == 1.0900


def test_update_peak_short_higher_price(db):
    em = _make_exit_manager(db=db)
    em._peak_prices["EUR_USD"] = 1.1000
    em._update_peak("EUR_USD", "short", 1.1200)
    assert em._peak_prices["EUR_USD"] == 1.1000


# ---------------------------------------------------------------------------
# _trailing_stop_reason
# ---------------------------------------------------------------------------

def test_trailing_stop_long_no_trigger(db, monkeypatch):
    monkeypatch.setattr(settings, "STOP_LOSS_PCT", 0.02)
    em = _make_exit_manager(db=db)
    em._peak_prices["SPY"] = 100.0
    reason = em._trailing_stop_reason("SPY", "long", 99.0)
    assert reason is None  # 1% < 2%


def test_trailing_stop_long_triggers(db, monkeypatch):
    monkeypatch.setattr(settings, "STOP_LOSS_PCT", 0.02)
    em = _make_exit_manager(db=db)
    em._peak_prices["SPY"] = 100.0
    reason = em._trailing_stop_reason("SPY", "long", 97.0)
    assert reason is not None
    assert "trailing stop" in reason


def test_trailing_stop_short_no_trigger(db, monkeypatch):
    monkeypatch.setattr(settings, "STOP_LOSS_PCT", 0.02)
    em = _make_exit_manager(db=db)
    em._peak_prices["EUR_USD"] = 1.1000
    reason = em._trailing_stop_reason("EUR_USD", "short", 1.1010)
    assert reason is None


def test_trailing_stop_short_triggers(db, monkeypatch):
    monkeypatch.setattr(settings, "STOP_LOSS_PCT", 0.02)
    em = _make_exit_manager(db=db)
    em._peak_prices["EUR_USD"] = 1.1000
    reason = em._trailing_stop_reason("EUR_USD", "short", 1.1300)
    assert reason is not None
    assert "trailing stop" in reason


def test_trailing_stop_no_peak(db):
    em = _make_exit_manager(db=db)
    reason = em._trailing_stop_reason("SPY", "long", 100.0)
    assert reason is None


def test_trailing_stop_zero_peak(db):
    em = _make_exit_manager(db=db)
    em._peak_prices["SPY"] = 0
    reason = em._trailing_stop_reason("SPY", "long", 100.0)
    assert reason is None


# ---------------------------------------------------------------------------
# _time_exit_reason
# ---------------------------------------------------------------------------

def test_time_exit_not_exceeded(db, monkeypatch):
    monkeypatch.setattr(settings, "MAX_HOLD_HOURS", 4.0)
    em = _make_exit_manager(db=db)
    _insert_executed_signal(db, ticker="SPY", hours_ago=1)
    reason = em._time_exit_reason("SPY")
    assert reason is None


def test_time_exit_exceeded(db, monkeypatch):
    monkeypatch.setattr(settings, "MAX_HOLD_HOURS", 2.0)
    em = _make_exit_manager(db=db)
    _insert_executed_signal(db, ticker="SPY", hours_ago=3)
    reason = em._time_exit_reason("SPY")
    assert reason is not None
    assert "time-based exit" in reason


def test_time_exit_no_signal(db):
    em = _make_exit_manager(db=db)
    reason = em._time_exit_reason("SPY")
    assert reason is None


def test_time_exit_no_executed_at(db):
    em = _make_exit_manager(db=db)
    # Save a signal but don't execute it (no executed_at)
    db.save_article(make_article(article_id=999))
    db.save_signal(make_signal(article_id=999, ticker="SPY"))
    reason = em._time_exit_reason("SPY")
    assert reason is None


# ---------------------------------------------------------------------------
# _evaluate
# ---------------------------------------------------------------------------

def test_evaluate_time_exit_takes_priority(db, monkeypatch):
    monkeypatch.setattr(settings, "MAX_HOLD_HOURS", 1.0)
    monkeypatch.setattr(settings, "STOP_LOSS_PCT", 0.02)
    monkeypatch.setattr("core.exit_manager.send_exit_alert", lambda *a, **kw: None)

    broker = FakeBroker(prices={"SPY": 95.0})
    em = _make_exit_manager(broker=broker, db=db)
    em._peak_prices["SPY"] = 100.0
    _insert_executed_signal(db, ticker="SPY", hours_ago=2)

    em._evaluate("SPY", "long", 95.0, is_forex=False)
    # Position should be closed due to time exit
    assert "SPY" in broker.closed_positions


def test_evaluate_trailing_stop_fires_when_no_time_exit(db, monkeypatch):
    monkeypatch.setattr(settings, "MAX_HOLD_HOURS", 10.0)
    monkeypatch.setattr(settings, "STOP_LOSS_PCT", 0.02)
    monkeypatch.setattr("core.exit_manager.send_exit_alert", lambda *a, **kw: None)

    broker = FakeBroker(prices={"SPY": 95.0})
    em = _make_exit_manager(broker=broker, db=db)
    em._peak_prices["SPY"] = 100.0
    _insert_executed_signal(db, ticker="SPY", hours_ago=1)

    em._evaluate("SPY", "long", 95.0, is_forex=False)
    # 5% drawdown > 2% -> trailing stop fires
    assert "SPY" in broker.closed_positions


# ---------------------------------------------------------------------------
# _close
# ---------------------------------------------------------------------------

def test_close_equity_calls_broker(db, monkeypatch):
    monkeypatch.setattr("core.exit_manager.send_exit_alert", lambda *a, **kw: None)
    broker = FakeBroker(prices={"SPY": 450.0})
    em = _make_exit_manager(broker=broker, db=db)
    _insert_executed_signal(db, ticker="SPY", hours_ago=1)

    em._close("SPY", "test reason", is_forex=False)
    assert "SPY" in broker.closed_positions


def test_close_forex_calls_forex_broker(db, monkeypatch):
    monkeypatch.setattr("core.exit_manager.send_exit_alert", lambda *a, **kw: None)
    forex = FakeForexBroker(prices={"EUR_USD": 1.1000})
    broker = FakeBroker()
    em = _make_exit_manager(broker=broker, db=db, forex=forex)
    _insert_executed_signal(db, ticker="EUR_USD", hours_ago=1)

    em._close("EUR_USD", "test reason", is_forex=True)
    assert "EUR_USD" in forex.closed_positions
    assert "EUR_USD" not in broker.closed_positions


def test_close_records_exit_price(db, monkeypatch):
    monkeypatch.setattr("core.exit_manager.send_exit_alert", lambda *a, **kw: None)
    broker = FakeBroker(prices={"SPY": 450.0})
    em = _make_exit_manager(broker=broker, db=db)
    sig_id = _insert_executed_signal(db, ticker="SPY", hours_ago=1)

    em._close("SPY", "test reason", is_forex=False)
    signal = db.get_last_executed_signal("SPY")
    assert signal["exit_price"] == 450.0


def test_close_clears_peak_tracking(db, monkeypatch):
    monkeypatch.setattr("core.exit_manager.send_exit_alert", lambda *a, **kw: None)
    broker = FakeBroker(prices={"SPY": 450.0})
    em = _make_exit_manager(broker=broker, db=db)
    em._peak_prices["SPY"] = 460.0
    _insert_executed_signal(db, ticker="SPY", hours_ago=1)

    em._close("SPY", "test reason", is_forex=False)
    assert "SPY" not in em._peak_prices
