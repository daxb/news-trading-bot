"""
Unit tests for core/alerts.py — Telegram alert sender.

All HTTP calls are monkeypatched — no Telegram API calls are made.

Run with:
    python -m pytest tests/test_alerts.py -v
"""

import pytest

from config import settings
from core import alerts


# ---------------------------------------------------------------------------
# send_signal_alert
# ---------------------------------------------------------------------------

def test_send_signal_alert_no_config_noop(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "")
    calls = []
    monkeypatch.setattr("core.alerts.requests.post", lambda *a, **kw: calls.append(1))
    alerts.send_signal_alert({"action": "buy", "ticker": "SPY", "confidence": 0.8, "theme": "test", "rationale": "test"})
    assert calls == []


def test_send_signal_alert_posts_correctly(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "123")

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr("core.alerts.requests.post", fake_post)
    alerts.send_signal_alert({
        "action": "buy", "ticker": "SPY", "confidence": 0.85,
        "theme": "fed_dovish", "rationale": "rate cut",
    })
    assert "fake-token" in captured["url"]
    assert captured["json"]["chat_id"] == "123"
    assert "BUY" in captured["json"]["text"]
    assert "SPY" in captured["json"]["text"]


# ---------------------------------------------------------------------------
# send_exit_alert
# ---------------------------------------------------------------------------

def test_send_exit_alert_no_config_noop(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "")
    calls = []
    monkeypatch.setattr("core.alerts.requests.post", lambda *a, **kw: calls.append(1))
    alerts.send_exit_alert("SPY", "trailing stop")
    assert calls == []


def test_send_exit_alert_posts_correctly(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "123")

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_post(url, json=None, timeout=None):
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr("core.alerts.requests.post", fake_post)
    alerts.send_exit_alert("SPY", "trailing stop", order_id="abc")
    assert "CLOSED SPY" in captured["json"]["text"]
    assert "trailing stop" in captured["json"]["text"]


# ---------------------------------------------------------------------------
# send_startup_alert
# ---------------------------------------------------------------------------

def test_send_startup_alert_posts(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "123")

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_post(url, json=None, timeout=None):
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr("core.alerts.requests.post", fake_post)
    alerts.send_startup_alert()
    assert "started" in captured["json"]["text"]


def test_send_startup_alert_no_config_noop(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "")
    calls = []
    monkeypatch.setattr("core.alerts.requests.post", lambda *a, **kw: calls.append(1))
    alerts.send_startup_alert()
    assert calls == []


# ---------------------------------------------------------------------------
# send_hourly_update
# ---------------------------------------------------------------------------

def test_send_hourly_update_formats_signals(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "123")

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_post(url, json=None, timeout=None):
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr("core.alerts.requests.post", fake_post)
    signals = [{"action": "buy", "ticker": "SPY", "confidence": 0.8, "theme": "test", "status": "executed"}]
    account = {"equity": 100000.0, "cash": 50000.0, "buying_power": 50000.0}
    alerts.send_hourly_update(signals, account, [])
    assert "SPY" in captured["json"]["text"]


def test_send_hourly_update_no_config_noop(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "")
    calls = []
    monkeypatch.setattr("core.alerts.requests.post", lambda *a, **kw: calls.append(1))
    alerts.send_hourly_update([], {}, [])
    assert calls == []


# ---------------------------------------------------------------------------
# send_audit_report
# ---------------------------------------------------------------------------

def test_send_audit_report_formats_metrics(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "123")

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_post(url, json=None, timeout=None):
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr("core.alerts.requests.post", fake_post)
    metrics = {
        "period_hours": 24,
        "signals": {"total": 10, "executed": 5, "skipped": 3, "skip_rate": 0.3},
        "pipeline": {"total_articles": 100, "by_source": {"Reuters": 50, "AP": 50}},
        "themes": {},
        "pnl_by_theme": {},
        "anomalies": [],
    }
    alerts.send_audit_report(metrics)
    assert "Audit" in captured["json"]["text"]
    assert "10 total" in captured["json"]["text"]
