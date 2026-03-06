"""
Telegram alert sender for the Macro Trader bot.

Sends a message to a configured chat when a trading signal is generated.
No-ops silently if TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID are not set.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

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


def send_hourly_update(
    signals: list[dict],
    account: dict,
    positions: list[dict],
    open_orders: list[dict] | None = None,
) -> None:
    """Send an hourly summary of signals, trades, and P&L to Telegram."""
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        logger.debug("Telegram not configured — skipping hourly update")
        return

    now_et = datetime.now(ZoneInfo("America/New_York"))
    header = f"*Hourly Update — {now_et.strftime('%H:%M')} ET*"

    # Signals section
    if signals:
        executed = [s for s in signals if s.get("status") == "executed"]

        sig_lines = [f"\n*Signals last 1h:* {len(signals)} total, {len(executed)} executed"]
        for s in signals[:8]:  # cap to avoid hitting Telegram's 4096-char limit
            status_icon = "✅" if s.get("status") == "executed" else "⏭"
            action = s.get("action", "").upper()
            ticker = s.get("ticker", "")
            conf = s.get("confidence", 0.0)
            theme = s.get("theme", "")
            sig_lines.append(f"  {status_icon} {action} `{ticker}` conf={conf:.2f} _{theme}_")
        if len(signals) > 8:
            sig_lines.append(f"  … and {len(signals) - 8} more")
    else:
        sig_lines = ["\n*Signals last 1h:* none"]

    # P&L / portfolio section
    equity = account.get("equity", 0.0)
    cash = account.get("cash", 0.0)
    buying_power = account.get("buying_power", 0.0)

    pnl_lines = [
        f"\n*Portfolio*",
        f"  Equity: `${equity:,.2f}`",
        f"  Cash:   `${cash:,.2f}`",
        f"  Buying power: `${buying_power:,.2f}`",
    ]

    total_unrealized = sum(p.get("unrealized_pl", 0.0) for p in positions)
    if positions:
        sign = "+" if total_unrealized >= 0 else ""
        pnl_lines.append(f"  Unrealized P&L: `{sign}${total_unrealized:,.2f}`")
        pnl_lines.append(f"\n*Open Positions ({len(positions)})*")
        for p in positions:
            sym = p.get("symbol", "")
            qty = p.get("qty", 0)
            upl = p.get("unrealized_pl", 0.0)
            uplpc = p.get("unrealized_plpc", 0.0) * 100
            sign = "+" if upl >= 0 else ""
            pnl_lines.append(
                f"  `{sym}` {qty} shares  {sign}${upl:,.2f} ({sign}{uplpc:.1f}%)"
            )
    else:
        pnl_lines.append("  No open positions")

    # Open orders section
    order_lines: list[str] = []
    if open_orders:
        order_lines.append(f"\n*Open Orders ({len(open_orders)})*")
        for o in open_orders:
            sym  = o.get("symbol", "")
            side = o.get("side", "").upper()
            qty  = o.get("qty", "")
            otype = o.get("type", "")
            order_lines.append(f"  `{sym}` {side} {qty} ({otype})")

    text = header + "\n".join(sig_lines) + "\n".join(pnl_lines) + "\n".join(order_lines)

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
        logger.info("Telegram hourly update sent")
    except Exception:
        logger.exception("Failed to send Telegram hourly update")


def send_startup_alert() -> None:
    """Notify Telegram that the bot has started."""
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        return
    try:
        resp = requests.post(
            _BASE_URL.format(token=settings.TELEGRAM_BOT_TOKEN),
            json={
                "chat_id": settings.TELEGRAM_CHAT_ID,
                "text": "🟢 *FIONA — started*",
                "parse_mode": "Markdown",
            },
            timeout=10,
        )
        resp.raise_for_status()
        logger.info("Telegram startup alert sent")
    except Exception:
        logger.exception("Failed to send Telegram startup alert")


def send_shutdown_alert() -> None:
    """Notify Telegram that the bot is shutting down."""
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        return
    try:
        resp = requests.post(
            _BASE_URL.format(token=settings.TELEGRAM_BOT_TOKEN),
            json={
                "chat_id": settings.TELEGRAM_CHAT_ID,
                "text": "🔴 *FIONA — shutting down*",
                "parse_mode": "Markdown",
            },
            timeout=10,
        )
        resp.raise_for_status()
        logger.info("Telegram shutdown alert sent")
    except Exception:
        logger.exception("Failed to send Telegram shutdown alert")


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
