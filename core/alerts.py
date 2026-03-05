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

    text = (
        f"*{action} {ticker}*\n"
        f"Theme: `{theme}`\n"
        f"Confidence: `{confidence:.2f}`\n"
        f"{rationale}"
    )

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
