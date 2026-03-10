"""
Audit metrics engine for FIONA.

Computes health and performance metrics over a rolling time window by
querying the local SQLite DB. No broker API calls — purely offline analysis.

Public API
----------
    metrics = compute_metrics(db, hours=24)

Return shape
------------
{
    "period_hours": int,
    "generated_at": str,           # UTC ISO-8601
    "signals": {
        "total": int,
        "executed": int,
        "skipped": int,
        "expired": int,
        "skip_rate": float,         # [0.0, 1.0]
        "expiry_rate": float,       # [0.0, 1.0]
    },
    "themes": {
        "<theme>": {
            "total": int,
            "executed": int,
            "skipped": int,
            "expired": int,
            "skip_rate": float,
            "avg_confidence": float,
            "skip_reasons": {"<reason>": int, ...},  # counts per skip reason
        },
        ...
    },
    "pipeline": {
        "total_articles": int,
        "by_source": {"<source>": int, ...},
        "articles_per_signal": float,
    },
    "pnl_by_theme": {               # only themes with fill_price + exit_price data
        "<theme>": {
            "count": int,
            "win_rate": float,
            "avg_return_pct": float,
        },
        ...
    },
    "anomalies": [str, ...],        # human-readable warning strings
}
"""

import logging
from datetime import datetime, timezone

from core.db import Database
from core.rss import _FEEDS as _RSS_FEEDS

logger = logging.getLogger(__name__)

# Derived from the live feed registry so this list never drifts out of sync.
# Adding or removing a feed in core/rss.py automatically updates this check.
_EXPECTED_SOURCES: set[str] = {f["name"] for f in _RSS_FEEDS} | {"finnhub"}


def _empty_metrics(hours: int) -> dict:
    """Return a valid but zeroed-out metrics dict for fallback."""
    return {
        "period_hours": hours,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "signals": {
            "total": 0,
            "executed": 0,
            "skipped": 0,
            "expired": 0,
            "skip_rate": 0.0,
            "expiry_rate": 0.0,
        },
        "themes": {},
        "pipeline": {
            "total_articles": 0,
            "by_source": {},
            "articles_per_signal": 0.0,
        },
        "pnl_by_theme": {},
        "anomalies": [],
    }


def compute_metrics(db: Database, hours: int = 24) -> dict:
    """
    Compute audit metrics for the last `hours` hours.

    Args:
        db:    Shared Database instance.
        hours: Rolling window to analyse (default 24h).

    Returns:
        Structured metrics dict — see module docstring for full shape.
    """
    logger.info("Computing audit metrics for last %dh", hours)

    # ------------------------------------------------------------------
    # Fetch raw data — fatal if this fails (everything depends on it)
    # ------------------------------------------------------------------
    try:
        signals = db.get_signals_since(hours=hours)
        articles = db.get_articles_since(hours=hours)
    except Exception:
        logger.exception("Failed to fetch data from DB for audit")
        return _empty_metrics(hours)

    # ------------------------------------------------------------------
    # Signal stats
    # ------------------------------------------------------------------
    try:
        total = len(signals)
        executed = [s for s in signals if s["status"] == "executed"]
        skipped = [s for s in signals if s["status"] == "skipped"]
        expired = [s for s in signals if s["status"] == "expired"]
        skip_rate = len(skipped) / total if total else 0.0
        expiry_rate = len(expired) / total if total else 0.0
    except Exception:
        logger.exception("Failed to compute signal stats")
        total = 0
        executed, skipped, expired = [], [], []
        skip_rate = 0.0
        expiry_rate = 0.0

    # ------------------------------------------------------------------
    # Per-theme breakdown
    # ------------------------------------------------------------------
    themes: dict[str, dict] = {}
    try:
        for sig in signals:
            theme = sig.get("theme") or "unknown"
            if theme not in themes:
                themes[theme] = {
                    "total": 0,
                    "executed": 0,
                    "skipped": 0,
                    "expired": 0,
                    "_conf_sum": 0.0,
                    "skip_reasons": {},
                }
            themes[theme]["total"] += 1
            themes[theme]["_conf_sum"] += float(sig.get("confidence") or 0.0)
            if sig["status"] == "executed":
                themes[theme]["executed"] += 1
            elif sig["status"] == "skipped":
                themes[theme]["skipped"] += 1
                reason = sig.get("skip_reason") or "unknown"
                themes[theme]["skip_reasons"][reason] = (
                    themes[theme]["skip_reasons"].get(reason, 0) + 1
                )
            elif sig["status"] == "expired":
                themes[theme]["expired"] += 1

        for theme, data in themes.items():
            t = data["total"]
            data["skip_rate"] = round(data["skipped"] / t, 4) if t else 0.0
            data["avg_confidence"] = round(data["_conf_sum"] / t, 4) if t else 0.0
            del data["_conf_sum"]
    except Exception:
        logger.exception("Failed to compute per-theme breakdown")
        themes = {}

    # ------------------------------------------------------------------
    # Pipeline health — articles by source
    # ------------------------------------------------------------------
    source_counts: dict[str, int] = {}
    try:
        for a in articles:
            src = a.get("source") or "unknown"
            source_counts[src] = source_counts.get(src, 0) + 1
    except Exception:
        logger.exception("Failed to compute article source counts")
        source_counts = {}

    # ------------------------------------------------------------------
    # P&L by theme (only where both fill_price and exit_price are recorded)
    # NOTE: Returns are simple price percentage, not dollar-weighted.
    # The signals table lacks a quantity column, so all trades are
    # treated equally regardless of position size.
    # ------------------------------------------------------------------
    pnl_by_theme: dict[str, dict] = {}
    try:
        for sig in executed:
            fill = sig.get("fill_price")
            exit_p = sig.get("exit_price")
            if not fill or not exit_p or fill == 0:
                continue
            theme = sig.get("theme") or "unknown"
            if theme not in pnl_by_theme:
                pnl_by_theme[theme] = {"_returns": [], "wins": 0, "losses": 0}
            # Directional return: positive means profitable
            if sig.get("action") == "buy":
                ret = (exit_p - fill) / fill
            else:
                ret = (fill - exit_p) / fill
            pnl_by_theme[theme]["_returns"].append(ret)
            if ret > 0:
                pnl_by_theme[theme]["wins"] += 1
            else:
                pnl_by_theme[theme]["losses"] += 1

        for theme, data in pnl_by_theme.items():
            returns = data["_returns"]
            count = len(returns)
            data["count"] = count
            data["win_rate"] = round(data["wins"] / count, 4) if count else 0.0
            data["avg_return_pct"] = round(sum(returns) / count * 100, 4) if count else 0.0
            del data["_returns"]
    except Exception:
        logger.exception("Failed to compute P&L by theme")
        pnl_by_theme = {}

    # ------------------------------------------------------------------
    # Anomaly detection
    # ------------------------------------------------------------------
    anomalies: list[str] = []
    try:
        # 1. High overall skip rate (only meaningful with enough data)
        if total >= 10 and skip_rate > 0.90:
            anomalies.append(
                f"High skip rate: {skip_rate:.0%} of {total} signals were skipped — "
                "check conviction threshold or risk limits"
            )

        # 2. Theme concentration: one theme dominates
        if total >= 5:
            for theme, data in themes.items():
                pct = data["total"] / total
                if pct > 0.60:
                    anomalies.append(
                        f"Theme concentration: '{theme}' = {pct:.0%} of all signals — "
                        "keyword rules may be over-firing"
                    )

        # 3. Missing sources — feed may be broken
        for src in _EXPECTED_SOURCES:
            if src not in source_counts:
                anomalies.append(
                    f"No articles from '{src}' in last {hours}h — feed may be broken"
                )

        # 4. Position accumulation: same ticker + direction 3+ consecutive executed signals
        executed_sorted = sorted(executed, key=lambda s: s.get("executed_at") or "")
        ticker_run: dict[str, tuple[str, int]] = {}  # ticker -> (action, count)
        for sig in executed_sorted:
            ticker = sig.get("ticker", "")
            action = sig.get("action", "")
            if ticker not in ticker_run:
                ticker_run[ticker] = (action, 1)
            else:
                prev_action, count = ticker_run[ticker]
                if prev_action == action:
                    ticker_run[ticker] = (action, count + 1)
                else:
                    ticker_run[ticker] = (action, 1)
        for ticker, (action, count) in ticker_run.items():
            if count >= 3:
                anomalies.append(
                    f"Position accumulation: {count} consecutive {action.upper()} "
                    f"executions for {ticker}"
                )

        # 5. Pipeline stall — no articles at all
        if not articles:
            anomalies.append(
                f"No articles ingested in last {hours}h — pipeline may be stalled"
            )

        # 6. Per-theme high skip rate (separate from overall)
        for theme, data in themes.items():
            if data["total"] >= 5 and data["skip_rate"] > 0.95:
                anomalies.append(
                    f"Theme '{theme}' skip rate {data['skip_rate']:.0%} "
                    f"({data['skipped']}/{data['total']}) — rule may be too noisy"
                )

        # 7. High expiry rate — signals timing out before execution
        if total >= 10 and expiry_rate > 0.30:
            anomalies.append(
                f"High expiry rate: {expiry_rate:.0%} of {total} signals expired — "
                "signals may be generated too far from execution windows"
            )
    except Exception:
        logger.exception("Failed to run anomaly detection")
        anomalies.append("Anomaly detection failed — see logs")

    return {
        "period_hours": hours,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "signals": {
            "total": total,
            "executed": len(executed),
            "skipped": len(skipped),
            "expired": len(expired),
            "skip_rate": round(skip_rate, 4),
            "expiry_rate": round(expiry_rate, 4),
        },
        "themes": themes,
        "pipeline": {
            "total_articles": len(articles),
            "by_source": source_counts,
            "articles_per_signal": round(len(articles) / total, 1) if total else 0.0,
        },
        "pnl_by_theme": pnl_by_theme,
        "anomalies": anomalies,
    }
