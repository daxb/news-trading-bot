"""
Unit tests for core/macro_context.py — regime-aware signal adjustment.

Uses FakeMacroClient to inject known indicator values.
No API keys, no network, no ML models required.

Run with:
    python -m pytest tests/test_macro_context.py -v
"""

import pytest

from tests.conftest import FakeMacroClient

from config import settings
from core.macro_context import MacroContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(indicators: dict) -> MacroContext:
    """Build a MacroContext with given FRED indicator values."""
    # Wrap raw values in the expected {"value": v} format
    wrapped = {k: {"value": v} for k, v in indicators.items()}
    client = FakeMacroClient(indicators=wrapped)
    return MacroContext(client)


def _make_signal(theme: str, confidence: float = 0.8) -> dict:
    return {
        "article_id": 1,
        "ticker": "SPY",
        "action": "buy",
        "confidence": confidence,
        "theme": theme,
        "rationale": "test",
    }


# ---------------------------------------------------------------------------
# _multiplier_for via adjust_signals
# ---------------------------------------------------------------------------

def test_fed_hawkish_high_rates_boosts():
    ctx = _make_ctx({"FEDFUNDS": 5.0})
    result = ctx.adjust_signals([_make_signal("fed_hawkish")])
    assert len(result) == 1
    assert result[0]["confidence"] > 0.8  # boosted by 1.2x


def test_fed_hawkish_low_rates_dampens():
    ctx = _make_ctx({"FEDFUNDS": 1.0})
    result = ctx.adjust_signals([_make_signal("fed_hawkish")])
    assert len(result) == 1
    assert result[0]["confidence"] < 0.8  # dampened by 0.6x


def test_fed_dovish_high_rates_boosts():
    ctx = _make_ctx({"FEDFUNDS": 5.0})
    result = ctx.adjust_signals([_make_signal("fed_dovish")])
    assert len(result) == 1
    assert result[0]["confidence"] > 0.8


def test_fed_dovish_near_zero_dampens():
    ctx = _make_ctx({"FEDFUNDS": 1.0})
    result = ctx.adjust_signals([_make_signal("fed_dovish")])
    assert len(result) == 1
    assert result[0]["confidence"] < 0.8


def test_recession_risk_high_unemployment():
    ctx = _make_ctx({"UNRATE": 6.0})
    result = ctx.adjust_signals([_make_signal("recession_risk")])
    assert len(result) == 1
    assert result[0]["confidence"] > 0.8


def test_recession_risk_low_unemployment():
    ctx = _make_ctx({"UNRATE": 3.5})
    result = ctx.adjust_signals([_make_signal("recession_risk")])
    assert len(result) == 1
    assert result[0]["confidence"] < 0.8


def test_yield_curve_inversion_recession():
    ctx = _make_ctx({"T10Y2Y": -0.5})
    result = ctx.adjust_signals([_make_signal("recession_risk")])
    assert len(result) == 1
    assert result[0]["confidence"] > 0.8


def test_yield_curve_normal_recession():
    ctx = _make_ctx({"T10Y2Y": 1.0})
    result = ctx.adjust_signals([_make_signal("recession_risk")])
    assert len(result) == 1
    assert result[0]["confidence"] < 0.8


def test_vix_high_geopolitical():
    ctx = _make_ctx({"VIXCLS": 30.0})
    result = ctx.adjust_signals([_make_signal("geopolitical_risk")])
    assert len(result) == 1
    assert result[0]["confidence"] > 0.8


def test_vix_high_dampens_rally():
    ctx = _make_ctx({"VIXCLS": 30.0})
    result = ctx.adjust_signals([_make_signal("market_rally")])
    assert len(result) == 1
    assert result[0]["confidence"] < 0.8


def test_multiple_rules_compound():
    """Multiple indicator conditions met → multipliers compound."""
    ctx = _make_ctx({"UNRATE": 6.0, "T10Y2Y": -0.5})
    result = ctx.adjust_signals([_make_signal("recession_risk")])
    assert len(result) == 1
    # UNRATE>5.5 → 1.2, T10Y2Y<0 → 1.25 → combined = 1.5
    assert result[0]["confidence"] == pytest.approx(0.8 * 1.2 * 1.25, abs=0.01)


def test_no_matching_indicators_returns_1():
    ctx = _make_ctx({})
    # No indicators → passes through unadjusted
    result = ctx.adjust_signals([_make_signal("fed_hawkish")])
    assert len(result) == 1
    assert result[0]["confidence"] == 0.8


# ---------------------------------------------------------------------------
# adjust_signals — threshold filtering
# ---------------------------------------------------------------------------

def test_adjust_signals_drops_below_threshold(monkeypatch):
    monkeypatch.setattr(settings, "SIGNAL_CONVICTION_THRESHOLD", 0.5)
    ctx = _make_ctx({"FEDFUNDS": 1.0})
    # 0.45 * 0.6 = 0.27 < 0.5 threshold
    result = ctx.adjust_signals([_make_signal("fed_hawkish", confidence=0.45)])
    assert len(result) == 0


def test_adjust_signals_no_indicators_passes_through():
    ctx = _make_ctx({})
    signals = [_make_signal("fed_hawkish"), _make_signal("recession_risk")]
    result = ctx.adjust_signals(signals)
    assert len(result) == 2


def test_adjust_signals_preserves_unmatched_themes():
    ctx = _make_ctx({"FEDFUNDS": 3.0})
    # "some_unknown_theme" has no matching rules → multiplier 1.0
    result = ctx.adjust_signals([_make_signal("some_unknown_theme")])
    assert len(result) == 1
    assert result[0]["confidence"] == 0.8


# ---------------------------------------------------------------------------
# tick
# ---------------------------------------------------------------------------

def test_tick_refreshes_on_cycle(monkeypatch):
    monkeypatch.setattr(settings, "MACRO_REFRESH_CYCLES", 3)
    client = FakeMacroClient(indicators={"FEDFUNDS": {"value": 5.0}})
    ctx = MacroContext(client)
    # tick 3 times to trigger refresh on the 3rd
    ctx.tick()
    ctx.tick()
    ctx.tick()  # cycle 3 → should refresh


def test_tick_skips_between_cycles(monkeypatch):
    monkeypatch.setattr(settings, "MACRO_REFRESH_CYCLES", 12)
    call_count = 0
    original_refresh = MacroContext.refresh

    def counting_refresh(self):
        nonlocal call_count
        call_count += 1
        original_refresh(self)

    monkeypatch.setattr(MacroContext, "refresh", counting_refresh)
    client = FakeMacroClient(indicators={"FEDFUNDS": {"value": 5.0}})
    ctx = MacroContext(client)
    initial_calls = call_count

    ctx.tick()  # cycle 1 — no refresh
    assert call_count == initial_calls
