"""
Unit tests for config/settings.py — validation of configuration values.

Run with:
    python -m pytest tests/test_settings.py -v
"""

import pytest


def test_validate_settings_rejects_negative_max_position_pct(monkeypatch):
    """MAX_POSITION_PCT <= 0 must raise ValueError at validation time."""
    from config import settings
    monkeypatch.setattr(settings, "MAX_POSITION_PCT", -0.1)
    with pytest.raises(ValueError, match="MAX_POSITION_PCT"):
        settings._validate_settings()


def test_validate_settings_rejects_conviction_above_one(monkeypatch):
    """SIGNAL_CONVICTION_THRESHOLD > 1.0 must raise ValueError."""
    from config import settings
    monkeypatch.setattr(settings, "SIGNAL_CONVICTION_THRESHOLD", 1.5)
    with pytest.raises(ValueError, match="SIGNAL_CONVICTION_THRESHOLD"):
        settings._validate_settings()


def test_validate_settings_rejects_zero_hold_hours(monkeypatch):
    """MAX_HOLD_HOURS <= 0 must raise ValueError."""
    from config import settings
    monkeypatch.setattr(settings, "MAX_HOLD_HOURS", 0)
    with pytest.raises(ValueError, match="MAX_HOLD_HOURS"):
        settings._validate_settings()


def test_validate_settings_rejects_low_poll_interval(monkeypatch):
    """NEWS_POLL_INTERVAL_SECONDS < 30 must raise ValueError."""
    from config import settings
    monkeypatch.setattr(settings, "NEWS_POLL_INTERVAL_SECONDS", 5)
    with pytest.raises(ValueError, match="NEWS_POLL_INTERVAL_SECONDS"):
        settings._validate_settings()


def test_validate_settings_passes_with_defaults():
    """Default settings must pass validation without raising."""
    from config import settings
    # Should not raise — defaults are sane
    settings._validate_settings()
