"""
Streamlit monitoring dashboard for the Macro Trader bot.

Displays live portfolio state, signal history, recent news, and macro
indicators — all sourced from the same SQLite DB and APIs used by the bot.

Run from the project root (venv active):
    streamlit run dashboard/app.py
"""

import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from core.broker import BrokerClient
from core.db import Database
from core.macro import MacroClient

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Macro Trader",
    page_icon="📈",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Cached resource connections (one instance per session)
# ---------------------------------------------------------------------------

@st.cache_resource
def get_db() -> Database:
    return Database()


@st.cache_resource
def get_broker() -> BrokerClient:
    return BrokerClient()


@st.cache_resource
def get_macro() -> MacroClient:
    return MacroClient()


# ---------------------------------------------------------------------------
# Data fetchers (cached with TTL so a manual refresh busts the cache)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=30)
def fetch_account() -> dict:
    return get_broker().get_account()


@st.cache_data(ttl=30)
def fetch_positions() -> list[dict]:
    return get_broker().get_positions()


@st.cache_data(ttl=30)
def fetch_open_orders() -> list[dict]:
    return get_broker().get_orders(status="open")


@st.cache_data(ttl=30)
def fetch_signals(limit: int, status: str | None) -> list[dict]:
    return get_db().get_signals(limit=limit, status=status or None)


@st.cache_data(ttl=30)
def fetch_articles(limit: int, sentiment: str | None) -> list[dict]:
    return get_db().get_articles(limit=limit, sentiment_label=sentiment or None)


# FRED data changes at most monthly — no need to hit the API more than once/hr.
@st.cache_data(ttl=3600)
def fetch_macro() -> dict:
    return get_macro().get_key_indicators()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STATUS_ICON = {"executed": "🟢", "skipped": "⚪", "pending": "🟡", "expired": "🔴"}
_SENTIMENT_ICON = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}
_ACTION_ICON = {"buy": "⬆️", "sell": "⬇️"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S UTC")


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("📈 Macro Trader")
    st.caption(f"Updated: {_utc_now()}")

    if st.button("🔄 Refresh", width='stretch'):
        st.cache_data.clear()
        st.rerun()

    st.divider()

    # Macro data is slow (FRED API) and changes infrequently — lazy-load it
    # behind an expander so it doesn't block the initial page render.
    with st.expander("Macro Indicators"):
        macro = fetch_macro()
        if macro:
            # (label, format_string)
            _MACRO_GROUPS: dict[str, list[tuple[str, str, str]]] = {
                "Policy": [
                    ("FEDFUNDS",  "Fed Funds Rate",       "{:.2f}%"),
                    ("PCEPILFE",  "Core PCE Index",       "{:.1f}"),
                    ("T5YIE",     "5-Yr Breakeven",       "{:.2f}%"),
                    ("CPIAUCSL",  "CPI Index",            "{:.1f}"),
                ],
                "Growth / Labour": [
                    ("UNRATE",    "Unemployment",         "{:.1f}%"),
                    ("ICSA",      "Initial Claims",       "{:,.0f}"),
                    ("UMCSENT",   "Consumer Sentiment",   "{:.1f}"),
                    ("GDP",       "GDP",                  "{:.0f}"),
                ],
                "Rates / Spreads": [
                    ("DGS10",         "10-Yr Yield",          "{:.2f}%"),
                    ("T10Y2Y",        "Yield Curve (10Y−2Y)", "{:.2f}%"),
                    ("BAMLH0A0HYM2",  "HY Credit Spreads",    "{:.2f}%"),
                ],
                "Risk / FX": [
                    ("VIXCLS",    "VIX",                  "{:.1f}"),
                    ("DTWEXBGS",  "USD Trade-Weighted",   "{:.1f}"),
                ],
            }
            for group, series_list in _MACRO_GROUPS.items():
                group_entries = [(s, lbl, fmt) for s, lbl, fmt in series_list if s in macro]
                if not group_entries:
                    continue
                st.caption(group)
                for key, label, fmt in group_entries:
                    entry = macro[key]
                    st.metric(label, fmt.format(entry["value"]), delta=None,
                              help=f"FRED {key} as of {entry['date']}")
        else:
            st.warning("Macro data unavailable")

    st.divider()
    st.caption(f"Paper trading: {'✅ ON' if settings.PAPER_TRADING else '🚨 OFF'}")

# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------

tab_portfolio, tab_signals, tab_news = st.tabs(["Portfolio", "Signals", "News"])

# ── Portfolio ────────────────────────────────────────────────────────────────

with tab_portfolio:
    # Fetch account and positions in parallel — both are network calls and
    # independent of each other, so there's no reason to wait serially.
    with st.spinner("Loading portfolio…"):
        with ThreadPoolExecutor(max_workers=3) as ex:
            f_account   = ex.submit(fetch_account)
            f_positions = ex.submit(fetch_positions)
            f_orders    = ex.submit(fetch_open_orders)
        account   = f_account.result()
        positions = f_positions.result()
        orders    = f_orders.result()

    if not account:
        st.error("Could not load account data — check Alpaca API keys.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Portfolio Value", f"${account.get('portfolio_value', 0):,.2f}")
        c2.metric("Cash",            f"${account.get('cash', 0):,.2f}")
        c3.metric("Buying Power",    f"${account.get('buying_power', 0):,.2f}")
        c4.metric("Equity",          f"${account.get('equity', 0):,.2f}")

    st.subheader("Open Positions")

    if not positions:
        st.info("No open positions.")
    else:
        rows = []
        for p in positions:
            rows.append({
                "Symbol":        p["symbol"],
                "Qty":           p["qty"],
                "Side":          p["side"],
                "Entry Price":   f"${p['avg_entry_price']:,.2f}",
                "Current Price": f"${p['current_price']:,.2f}",
                "Market Value":  f"${p['market_value']:,.2f}",
                "Unrealized P&L": f"${p['unrealized_pl']:,.2f}",
                "P&L %":         f"{p['unrealized_plpc'] * 100:.2f}%",
            })
        st.dataframe(rows, width='stretch', hide_index=True)

    st.subheader("Open Orders")

    if not orders:
        st.info("No open orders.")
    else:
        order_rows = []
        for o in orders:
            order_rows.append({
                "Order ID": o["id"][:8] + "…",
                "Symbol":   o["symbol"],
                "Side":     o["side"],
                "Qty":      o["qty"],
                "Type":     o["type"],
                "Status":   o["status"],
                "Submitted": o["submitted_at"][:19] if o["submitted_at"] else "",
            })
        st.dataframe(order_rows, width='stretch', hide_index=True)

# ── Signals ──────────────────────────────────────────────────────────────────

@st.fragment
def render_signals_tab() -> None:
    """Isolated fragment so slider/filter changes only re-run this section."""
    col_f1, col_f2 = st.columns([1, 3])
    with col_f1:
        status_filter = st.selectbox(
            "Status", ["All", "executed", "pending", "skipped", "expired"]
        )
    with col_f2:
        sig_limit = st.slider("Show last N signals", 10, 200, 50)

    signals = fetch_signals(sig_limit, None if status_filter == "All" else status_filter)

    executed = sum(1 for s in signals if s["status"] == "executed")
    skipped  = sum(1 for s in signals if s["status"] == "skipped")
    pending  = sum(1 for s in signals if s["status"] == "pending")

    m1, m2, m3 = st.columns(3)
    m1.metric("Executed", executed)
    m2.metric("Skipped",  skipped)
    m3.metric("Pending",  pending)

    if not signals:
        st.info("No signals found.")
    else:
        rows = []
        for s in signals:
            rows.append({
                "":           _STATUS_ICON.get(s["status"], ""),
                "Action":     f"{_ACTION_ICON.get(s['action'], '')} {s['action'].upper()}",
                "Ticker":     s["ticker"],
                "Theme":      s["theme"],
                "Confidence": f"{s['confidence']:.2f}",
                "Status":     s["status"],
                "Created":    s["created_at"][:19] if s["created_at"] else "",
                "Executed":   s["executed_at"][:19] if s["executed_at"] else "—",
                "Rationale":  s["rationale"],
            })
        st.dataframe(rows, width='stretch', hide_index=True)


# ── News ─────────────────────────────────────────────────────────────────────

@st.fragment
def render_news_tab() -> None:
    """Isolated fragment so slider/filter changes only re-run this section."""
    col_n1, col_n2 = st.columns([1, 3])
    with col_n1:
        sentiment_filter = st.selectbox(
            "Sentiment", ["All", "positive", "negative", "neutral"]
        )
    with col_n2:
        news_limit = st.slider("Show last N articles", 10, 200, 50)

    articles = fetch_articles(
        news_limit, None if sentiment_filter == "All" else sentiment_filter
    )

    pos = sum(1 for a in articles if a.get("sentiment_label") == "positive")
    neg = sum(1 for a in articles if a.get("sentiment_label") == "negative")
    neu = sum(1 for a in articles if a.get("sentiment_label") == "neutral")

    a1, a2, a3 = st.columns(3)
    a1.metric("🟢 Positive", pos)
    a2.metric("🔴 Negative", neg)
    a3.metric("⚪ Neutral",  neu)

    if not articles:
        st.info("No articles found.")
    else:
        rows = []
        for a in articles:
            rows.append({
                "":          _SENTIMENT_ICON.get(a.get("sentiment_label", ""), ""),
                "Headline":  a["headline"],
                "Source":    a["source"],
                "Sentiment": a.get("sentiment_label", ""),
                "Score":     f"{a.get('sentiment_score', 0):.2f}",
                "Date":      (a["datetime"] or "")[:19],
            })
        st.dataframe(rows, width='stretch', hide_index=True)


with tab_signals:
    render_signals_tab()

with tab_news:
    render_news_tab()
