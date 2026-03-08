"""
Unit tests for core/backtester.py — TradeResult and WindowResult dataclasses.

Pure math tests — no yfinance, no network, no DB required.

Run with:
    python -m pytest tests/test_backtester.py -v
"""

import pytest
from datetime import datetime, timezone

yfinance = pytest.importorskip("yfinance", reason="yfinance not installed")
from core.backtester import TradeResult, WindowResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trade(entry_price: float, exit_price: float, action: str = "buy") -> TradeResult:
    return TradeResult(
        signal_id=1,
        ticker="SPY",
        action=action,
        theme="test",
        confidence=0.8,
        entry_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        exit_time=datetime(2026, 1, 1, 4, tzinfo=timezone.utc),
        entry_price=entry_price,
        exit_price=exit_price,
    )


# ---------------------------------------------------------------------------
# TradeResult.pnl_pct
# ---------------------------------------------------------------------------

def test_trade_result_pnl_buy_profit():
    t = _trade(100.0, 110.0, action="buy")
    assert t.pnl_pct == pytest.approx(0.10)
    assert t.correct is True


def test_trade_result_pnl_buy_loss():
    t = _trade(100.0, 90.0, action="buy")
    assert t.pnl_pct == pytest.approx(-0.10)
    assert t.correct is False


def test_trade_result_pnl_sell_profit():
    t = _trade(100.0, 90.0, action="sell")
    assert t.pnl_pct == pytest.approx(0.10)


def test_trade_result_pnl_sell_loss():
    t = _trade(100.0, 110.0, action="sell")
    assert t.pnl_pct == pytest.approx(-0.10)


def test_trade_result_pnl_zero_entry():
    t = _trade(0.0, 110.0, action="buy")
    assert t.pnl_pct == 0.0


# ---------------------------------------------------------------------------
# WindowResult properties
# ---------------------------------------------------------------------------

def test_window_result_win_rate():
    w = WindowResult(
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 1, 8, tzinfo=timezone.utc),
        trades=[
            _trade(100, 110),  # win
            _trade(100, 105),  # win
            _trade(100, 90),   # loss
        ],
    )
    assert w.win_rate == pytest.approx(2 / 3)


def test_window_result_max_drawdown():
    w = WindowResult(
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 1, 8, tzinfo=timezone.utc),
        trades=[
            _trade(100, 110),  # +10%
            _trade(100, 80),   # -20%
            _trade(100, 105),  # +5%
        ],
    )
    assert w.max_drawdown_pct > 0


def test_window_result_profit_factor():
    w = WindowResult(
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 1, 8, tzinfo=timezone.utc),
        trades=[
            _trade(100, 120),  # +20%
            _trade(100, 90),   # -10%
        ],
    )
    # profit=0.2, loss=0.1 -> factor=2.0
    assert w.profit_factor == pytest.approx(2.0)


def test_window_result_profit_factor_no_losses():
    w = WindowResult(
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 1, 8, tzinfo=timezone.utc),
        trades=[_trade(100, 110)],
    )
    assert w.profit_factor == float("inf")


def test_window_result_empty():
    w = WindowResult(
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 1, 8, tzinfo=timezone.utc),
    )
    assert w.win_rate == 0.0
    assert w.avg_return_pct == 0.0
    assert w.max_drawdown_pct == 0.0
    assert w.profit_factor == 0.0
