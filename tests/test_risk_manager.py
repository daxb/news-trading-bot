"""
Unit tests for core/risk_manager.py — position sizing and risk guards.

All external collaborators replaced with FakeBroker + in-memory DB.
No API keys, no network, no ML models required.

Run with:
    python -m pytest tests/test_risk_manager.py -v
"""

import pytest
from tests.conftest import FakeBroker, make_article, make_signal

from config import settings
from core.risk_manager import RiskManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_risk_manager(broker=None, db=None):
    """Build a RiskManager with injected fakes."""
    rm = RiskManager.__new__(RiskManager)
    rm._broker = broker or FakeBroker()
    rm._db = db
    rm._start_equity = rm._broker.equity
    return rm


# ---------------------------------------------------------------------------
# can_trade — daily trade limit
# ---------------------------------------------------------------------------

def test_can_trade_under_daily_limit(db):
    rm = _make_risk_manager(broker=FakeBroker(), db=db)
    ok, reason = rm.can_trade()
    assert ok is True
    assert reason == ""


def test_can_trade_at_daily_limit(db, monkeypatch):
    monkeypatch.setattr(settings, "MAX_TRADES_PER_DAY", 2)
    rm = _make_risk_manager(broker=FakeBroker(), db=db)
    # Insert 2 executed signals for today
    db.save_article(make_article(article_id=1))
    db.save_article(make_article(article_id=2))
    for i in [1, 2]:
        sid = db.save_signal(make_signal(article_id=i))
        from datetime import datetime, timezone
        db.update_signal_status(sid, "executed", executed_at=datetime.now(timezone.utc).isoformat())

    ok, reason = rm.can_trade()
    assert ok is False
    assert "Daily trade limit" in reason


def test_can_trade_above_daily_limit(db, monkeypatch):
    monkeypatch.setattr(settings, "MAX_TRADES_PER_DAY", 1)
    rm = _make_risk_manager(broker=FakeBroker(), db=db)
    db.save_article(make_article(article_id=1))
    db.save_article(make_article(article_id=2))
    for i in [1, 2]:
        sid = db.save_signal(make_signal(article_id=i))
        from datetime import datetime, timezone
        db.update_signal_status(sid, "executed", executed_at=datetime.now(timezone.utc).isoformat())

    ok, reason = rm.can_trade()
    assert ok is False


# ---------------------------------------------------------------------------
# can_trade — daily loss
# ---------------------------------------------------------------------------

def test_can_trade_daily_loss_below_limit(db, monkeypatch):
    monkeypatch.setattr(settings, "MAX_DAILY_LOSS_PCT", 0.05)
    broker = FakeBroker(equity=98_000.0)
    rm = _make_risk_manager(broker=broker, db=db)
    rm._start_equity = 100_000.0
    # 2% loss < 5% limit
    ok, reason = rm.can_trade()
    assert ok is True


def test_can_trade_daily_loss_at_limit(db, monkeypatch):
    monkeypatch.setattr(settings, "MAX_DAILY_LOSS_PCT", 0.03)
    broker = FakeBroker(equity=97_000.0)
    rm = _make_risk_manager(broker=broker, db=db)
    rm._start_equity = 100_000.0
    ok, reason = rm.can_trade()
    assert ok is False
    assert "Daily loss limit" in reason


def test_can_trade_daily_loss_above_limit(db, monkeypatch):
    monkeypatch.setattr(settings, "MAX_DAILY_LOSS_PCT", 0.03)
    broker = FakeBroker(equity=95_000.0)
    rm = _make_risk_manager(broker=broker, db=db)
    rm._start_equity = 100_000.0
    ok, reason = rm.can_trade()
    assert ok is False


def test_can_trade_no_equity_drop(db):
    broker = FakeBroker(equity=100_000.0)
    rm = _make_risk_manager(broker=broker, db=db)
    rm._start_equity = 100_000.0
    ok, _ = rm.can_trade()
    assert ok is True


# ---------------------------------------------------------------------------
# can_trade — per-ticker accumulation guard
# ---------------------------------------------------------------------------

def test_can_trade_blocks_duplicate_buy(db):
    broker = FakeBroker(
        position_map={"SPY": {"symbol": "SPY", "qty": 10.0, "side": "long"}}
    )
    rm = _make_risk_manager(broker=broker, db=db)
    ok, reason = rm.can_trade(ticker="SPY", action="buy")
    assert ok is False
    assert "Already hold a position" in reason


def test_can_trade_allows_buy_no_existing_position(db):
    broker = FakeBroker(position_map={})
    rm = _make_risk_manager(broker=broker, db=db)
    ok, _ = rm.can_trade(ticker="SPY", action="buy")
    assert ok is True


def test_can_trade_allows_sell_with_existing_position(db):
    broker = FakeBroker(
        position_map={"SPY": {"symbol": "SPY", "qty": 10.0, "side": "long"}}
    )
    rm = _make_risk_manager(broker=broker, db=db)
    ok, _ = rm.can_trade(ticker="SPY", action="sell")
    assert ok is True


def test_can_trade_no_ticker_skips_accumulation_check(db):
    broker = FakeBroker(
        position_map={"SPY": {"symbol": "SPY", "qty": 10.0, "side": "long"}}
    )
    rm = _make_risk_manager(broker=broker, db=db)
    ok, _ = rm.can_trade(ticker=None, action=None)
    assert ok is True


# ---------------------------------------------------------------------------
# position_qty
# ---------------------------------------------------------------------------

def test_position_qty_normal(db, monkeypatch):
    monkeypatch.setattr(settings, "MAX_POSITION_PCT", 0.05)
    broker = FakeBroker(equity=100_000.0, prices={"SPY": 500.0})
    rm = _make_risk_manager(broker=broker, db=db)
    qty = rm.position_qty("SPY")
    assert qty == 10.0


def test_position_qty_zero_equity(db, monkeypatch):
    monkeypatch.setattr(settings, "MAX_POSITION_PCT", 0.05)
    broker = FakeBroker(equity=0.0, prices={"SPY": 500.0})
    rm = _make_risk_manager(broker=broker, db=db)
    qty = rm.position_qty("SPY")
    assert qty == 0.0


def test_position_qty_no_price(db, monkeypatch):
    monkeypatch.setattr(settings, "MAX_POSITION_PCT", 0.05)
    broker = FakeBroker(equity=100_000.0, prices={})
    rm = _make_risk_manager(broker=broker, db=db)
    qty = rm.position_qty("SPY")
    assert qty == 0.0


def test_position_qty_below_minimum(db, monkeypatch):
    monkeypatch.setattr(settings, "MAX_POSITION_PCT", 0.001)
    # equity 100, price 100_000 -> 0.001 * 100 / 100_000 = 0.000001 < 0.01
    broker = FakeBroker(equity=100.0, prices={"SPY": 100_000.0})
    rm = _make_risk_manager(broker=broker, db=db)
    qty = rm.position_qty("SPY")
    assert qty == 0.0


def test_position_qty_rounds_to_two_decimals(db, monkeypatch):
    monkeypatch.setattr(settings, "MAX_POSITION_PCT", 0.05)
    broker = FakeBroker(equity=100_000.0, prices={"SPY": 333.33})
    rm = _make_risk_manager(broker=broker, db=db)
    qty = rm.position_qty("SPY")
    # 5000 / 333.33 = 15.00015... -> 15.0
    assert qty == round(5000.0 / 333.33, 2)


# ---------------------------------------------------------------------------
# _load_or_init_session_equity
# ---------------------------------------------------------------------------

def test_session_equity_fresh_start(db):
    """No stored date → fetches from broker and persists."""
    broker = FakeBroker(equity=50_000.0)
    rm = RiskManager.__new__(RiskManager)
    rm._broker = broker
    rm._db = db
    equity = rm._load_or_init_session_equity()
    assert equity == 50_000.0
    assert db.get_state("session_equity_value") == "50000.0"


def test_session_equity_restores_from_db(db):
    """Stored date == today → returns stored value."""
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    db.set_state("session_equity_date", today)
    db.set_state("session_equity_value", "75000.0")

    broker = FakeBroker(equity=80_000.0)
    rm = RiskManager.__new__(RiskManager)
    rm._broker = broker
    rm._db = db
    equity = rm._load_or_init_session_equity()
    assert equity == 75_000.0  # restored, not re-fetched


def test_session_equity_new_day_resets(db):
    """Stored date != today → re-fetches from broker."""
    db.set_state("session_equity_date", "2020-01-01")
    db.set_state("session_equity_value", "60000.0")

    broker = FakeBroker(equity=85_000.0)
    rm = RiskManager.__new__(RiskManager)
    rm._broker = broker
    rm._db = db
    equity = rm._load_or_init_session_equity()
    assert equity == 85_000.0
