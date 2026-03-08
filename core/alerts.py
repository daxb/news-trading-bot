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
_TELEGRAM_MAX_LENGTH = 4096


def _send_telegram(text: str, context: str) -> None:
    """Send a message to Telegram with truncation and error handling."""
    if len(text) > _TELEGRAM_MAX_LENGTH:
        text = text[:_TELEGRAM_MAX_LENGTH - 6] + "\n…"
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
        logger.info("Telegram %s sent", context)
    except requests.RequestException as e:
        logger.warning("Telegram request failed (%s): %s", context, e)
    except Exception:
        logger.exception("Failed to send Telegram %s", context)


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

    _send_telegram(text, f"signal alert: {action} {ticker}")


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

    _send_telegram(text, "hourly update")


def send_startup_alert() -> None:
    """Notify Telegram that the bot has started."""
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        return
    _send_telegram("🟢 *FIONA — started*", "startup alert")


def send_shutdown_alert() -> None:
    """Notify Telegram that the bot is shutting down."""
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        return
    _send_telegram("🔴 *FIONA — shutting down*", "shutdown alert")


def send_audit_report(metrics: dict) -> None:
    """Send the daily audit report to Telegram."""
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        logger.debug("Telegram not configured — skipping audit report")
        return

    hours = metrics.get("period_hours", 24)
    sigs = metrics.get("signals", {})
    pipeline = metrics.get("pipeline", {})
    themes = metrics.get("themes", {})
    pnl = metrics.get("pnl_by_theme", {})
    anomalies = metrics.get("anomalies", [])

    total = sigs.get("total", 0)
    executed = sigs.get("executed", 0)
    skipped = sigs.get("skipped", 0)
    skip_rate = sigs.get("skip_rate", 0.0)

    lines = [f"*FIONA Audit — last {hours}h*\n"]

    # Signals summary
    lines.append(
        f"*Signals*  {total} total | {executed} executed | {skipped} skipped "
        f"| skip rate {skip_rate:.0%}"
    )

    # Per-theme breakdown (sorted by total desc, cap at 8)
    if themes:
        lines.append("\n*By Theme*")
        for theme, data in sorted(themes.items(), key=lambda x: -x[1]["total"])[:8]:
            lines.append(
                f"  `{theme}`: {data['executed']} exec / {data['total']} total "
                f"({data['skip_rate']:.0%} skip, conf {data['avg_confidence']:.2f})"
            )

    # Pipeline health
    total_articles = pipeline.get("total_articles", 0)
    by_source = pipeline.get("by_source", {})
    src_str = "  " + " | ".join(
        f"{src}: {cnt}" for src, cnt in sorted(by_source.items(), key=lambda x: -x[1])
    )
    lines.append(f"\n*Pipeline*  {total_articles} articles")
    if by_source:
        lines.append(src_str)

    # P&L by theme
    if pnl:
        lines.append("\n*P&L by Theme* (closed trades)")
        for theme, data in sorted(pnl.items(), key=lambda x: -x[1]["count"]):
            sign = "+" if data["avg_return_pct"] >= 0 else ""
            lines.append(
                f"  `{theme}`: {data['count']} trades | "
                f"win {data['win_rate']:.0%} | {sign}{data['avg_return_pct']:.2f}% avg"
            )

    # Anomalies
    if anomalies:
        lines.append("\n*Anomalies*")
        for a in anomalies:
            lines.append(f"  • {a}")

    text = "\n".join(lines)

    _send_telegram(text, "audit report")


def send_exit_alert(ticker: str, reason: str, order_id: str = "") -> None:
    """Post a position-exit notification to Telegram."""
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        logger.debug("Telegram not configured — skipping exit alert")
        return

    text = f"🔴 *CLOSED {ticker}*\nReason: {reason}"
    if order_id:
        text += f"\nOrder: `{order_id}`"

    _send_telegram(text, f"exit alert: {ticker}")
