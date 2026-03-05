"""
Telegram alert sender for the Macro Trader bot.

Sends a message to a configured chat when a trading signal is generated.
No-ops silently if TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID are not set.
"""

import logging

import requests

from config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"


def send_signal_alert(signal: dict) -> None:
    """Post a signal notification to Telegram. Fails silently on error."""
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        logger.debug("Telegram not configured — skipping alert")
        return

    action = signal.get("action", "").upper()
    ticker = signal.get("ticker", "")
    confidence = signal.get("confidence", 0.0)
    theme = signal.get("theme", "")
    rationale = signal.get("rationale", "")
    qty = signal.get("qty")
    order_id = signal.get("order_id")

    header = f"*{action} {ticker}*"
    if qty:
        header += f" — {qty} shares"

    text = (
        f"{header}\n"
        f"Theme: `{theme}`\n"
        f"Confidence: `{confidence:.2f}`\n"
        f"{rationale}"
    )
    if order_id:
        text += f"\nOrder: `{order_id}`"

    try:
        resp = requests.post(
            _BASE_URL.format(token=settings.TELEGRAM_BOT_TOKEN),
            json={
                "chat_id": settings.TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "Markdown",
            },
            timeout=10,
        )
        resp.raise_for_status()
        logger.info("Telegram alert sent: %s %s", action, ticker)
    except Exception:
        logger.exception("Failed to send Telegram alert")


def send_exit_alert(ticker: str, reason: str, order_id: str = "") -> None:
    """Post a position-exit notification to Telegram."""
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        logger.debug("Telegram not configured — skipping exit alert")
        return

    text = f"🔴 *CLOSED {ticker}*\nReason: {reason}"
    if order_id:
        text += f"\nOrder: `{order_id}`"

    try:
        resp = requests.post(
            _BASE_URL.format(token=settings.TELEGRAM_BOT_TOKEN),
            json={
                "chat_id": settings.TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "Markdown",
            },
            timeout=10,
        )
        resp.raise_for_status()
        logger.info("Telegram exit alert sent: %s", ticker)
    except Exception:
        logger.exception("Failed to send Telegram exit alert")
