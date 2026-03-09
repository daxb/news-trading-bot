"""
Streamlit monitoring dashboard for the FIONA bot.

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
from core.auditor import compute_metrics
from core.broker import BrokerClient
from core.db import Database
from core.forex import ForexBroker
from core.macro import MacroClient

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="FIONA",
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


@st.cache_resource
def get_forex() -> ForexBroker | None:
    try:
        return ForexBroker()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Warm all API clients in parallel on cold start
# ---------------------------------------------------------------------------

def _warm_clients() -> None:
    with ThreadPoolExecutor(max_workers=3) as ex:
        ex.submit(get_broker)
        ex.submit(get_macro)
        ex.submit(get_forex)

_warm_clients()

# ---------------------------------------------------------------------------
# Data fetchers (cached with TTL so a manual refresh busts the cache)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60)
def fetch_account() -> dict:
    return get_broker().get_account()


@st.cache_data(ttl=60)
def fetch_forex_account() -> dict:
    client = get_forex()
    return client.get_account() if client else {}


@st.cache_data(ttl=45)
def fetch_positions() -> list[dict]:
    return get_broker().get_positions()


@st.cache_data(ttl=45)
def fetch_forex_positions() -> list[dict]:
    client = get_forex()
    return client.get_positions() if client else []


@st.cache_data(ttl=90)
def fetch_open_orders() -> list[dict]:
    return get_broker().get_orders(status="open")


@st.cache_data(ttl=120)
def fetch_closed_orders(limit: int) -> list[dict]:
    alpaca = get_broker().get_orders(status="closed")
    forex_client = get_forex()
    oanda = forex_client.get_recent_trades(limit=limit) if forex_client else []
    combined = sorted(
        alpaca + oanda,
        key=lambda o: o.get("filled_at") or o.get("submitted_at") or "",
        reverse=True,
    )
    return combined[:limit]


@st.cache_data(ttl=60)
def fetch_signals(limit: int, status: str | None) -> list[dict]:
    return get_db().get_signals(limit=limit, status=status or None)


@st.cache_data(ttl=60)
def fetch_articles(limit: int, sentiment: str | None) -> list[dict]:
    return get_db().get_articles(limit=limit, sentiment_label=sentiment or None)


# FRED data changes at most monthly — no need to hit the API more than once/hr.
@st.cache_data(ttl=3600)
def fetch_macro() -> dict:
    return get_macro().get_key_indicators()


@st.cache_data(ttl=300)
def fetch_portfolio_history(period: str, timeframe: str) -> dict:
    return get_broker().get_portfolio_history(period=period, timeframe=timeframe)


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
    st.title("📈 FIONA")
    st.caption(f"Updated: {_utc_now()}")

    col_r1, col_r2 = st.columns(2)
    with col_r1:
        if st.button("🔄 Refresh", use_container_width=True, help="Refresh trading data (keeps macro/FRED cache)"):
            fetch_account.clear()
            fetch_forex_account.clear()
            fetch_positions.clear()
            fetch_forex_positions.clear()
            fetch_open_orders.clear()
            fetch_closed_orders.clear()
            fetch_signals.clear()
            fetch_articles.clear()
            st.rerun()
    with col_r2:
        if st.button("🔄 Refresh + Macro", use_container_width=True, help="Refresh everything including macro/FRED data (slower)"):
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

tab_portfolio, tab_signals, tab_news, tab_audit = st.tabs(["Portfolio", "Signals", "News", "Audit"])

# ── Portfolio ────────────────────────────────────────────────────────────────

with tab_portfolio:
    # Fetch account and positions in parallel — both are network calls and
    # independent of each other, so there's no reason to wait serially.
    with st.spinner("Loading portfolio…"):
        with ThreadPoolExecutor(max_workers=5) as ex:
            f_account        = ex.submit(fetch_account)
            f_forex_account  = ex.submit(fetch_forex_account)
            f_positions      = ex.submit(fetch_positions)
            f_forex_positions = ex.submit(fetch_forex_positions)
            f_orders         = ex.submit(fetch_open_orders)
        account         = f_account.result()
        forex_account   = f_forex_account.result()
        positions       = f_positions.result()
        forex_positions = f_forex_positions.result()
        orders          = f_orders.result()

    if not account:
        st.error("Could not load account data — check Alpaca API keys.")
    else:
        alpaca_equity   = account.get("equity", 0)
        oanda_equity    = forex_account.get("equity", 0)
        total_equity    = alpaca_equity + oanda_equity

        last_equity     = account.get("last_equity", 0)
        daily_pl        = alpaca_equity - last_equity
        daily_pct       = (daily_pl / last_equity * 100) if last_equity else 0

        oanda_unreal_pl = sum(p.get("unrealized_pl", 0) for p in forex_positions)

        created_at_raw = account.get("created_at", "")
        try:
            created_dt = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
            days_active = (datetime.now(timezone.utc) - created_dt).days
        except (ValueError, TypeError):
            days_active = None

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Equity",       f"${total_equity:,.2f}",
                  help="Alpaca + OANDA combined")
        c2.metric("Alpaca Equity",       f"${alpaca_equity:,.2f}")
        c3.metric("OANDA NAV",           f"${oanda_equity:,.2f}" if forex_account else "—",
                  help="OANDA account NAV (not available if OANDA keys absent)")
        c4.metric("Days Active",         str(days_active) if days_active is not None else "—")

        d1, d2, d3, d4 = st.columns(4)
        d1.metric(
            "Alpaca Cash",
            f"${account.get('cash', 0):,.2f}",
        )
        d2.metric(
            "OANDA Cash",
            f"${forex_account.get('cash', 0):,.2f}" if forex_account else "—",
        )
        d3.metric(
            "Alpaca Daily P&L",
            f"${daily_pl:+,.2f}",
            delta=f"{daily_pct:+.2f}%",
            delta_color="normal",
        )
        d4.metric(
            "OANDA Unrealized P&L",
            f"${oanda_unreal_pl:+,.2f}" if forex_account else "—",
            help="Sum of unrealized P&L across all open OANDA positions",
        )

    @st.fragment
    def render_performance_charts() -> None:
        _TIMEFRAME_MAP = {"1D": "5Min", "1W": "1H", "1M": "1D", "3M": "1D", "1A": "1D"}
        st.subheader("Performance")
        perf_period = st.selectbox(
            "Period", list(_TIMEFRAME_MAP.keys()), index=2,
            key="perf_period", label_visibility="collapsed",
        )
        history = fetch_portfolio_history(perf_period, _TIMEFRAME_MAP[perf_period])
        if not history:
            st.info("Portfolio history unavailable.")
            return
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            st.caption("Portfolio Value ($)")
            st.line_chart(
                {"Date": history["dates"], "Value ($)": history["equity"]},
                x="Date", y="Value ($)", height=250,
            )
        with col_c2:
            st.caption("Return (%)")
            st.line_chart(
                {"Date": history["dates"], "Return (%)": history["profit_loss_pct"]},
                x="Date", y="Return (%)", height=250,
            )

    render_performance_charts()

    st.subheader("Open Positions")

    all_position_rows = []
    for p in positions:
        all_position_rows.append({
            "Broker":         "Alpaca",
            "Symbol":         p["symbol"],
            "Qty":            p["qty"],
            "Side":           p["side"],
            "Entry Price":    f"${p['avg_entry_price']:,.2f}",
            "Current Price":  f"${p['current_price']:,.2f}",
            "Market Value":   f"${p['market_value']:,.2f}",
            "Unrealized P&L": f"${p['unrealized_pl']:,.2f}",
            "P&L %":          f"{p['unrealized_plpc'] * 100:.2f}%",
        })
    for p in forex_positions:
        all_position_rows.append({
            "Broker":         "OANDA",
            "Symbol":         p["instrument"],
            "Qty":            str(abs(p["units"])),
            "Side":           p["side"],
            "Entry Price":    "—",
            "Current Price":  "—",
            "Market Value":   "—",
            "Unrealized P&L": f"${p['unrealized_pl']:,.2f}",
            "P&L %":          "—",
        })

    if not all_position_rows:
        st.info("No open positions.")
    else:
        st.dataframe(all_position_rows, use_container_width=True, hide_index=True)

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
        st.dataframe(order_rows, use_container_width=True, hide_index=True)

    @st.fragment
    def render_recent_trades() -> None:
        col_t1, col_t2 = st.columns([3, 1])
        with col_t1:
            st.subheader("Recent Trades")
        with col_t2:
            trade_limit = st.slider("Last N trades", 5, 100, 20, key="trade_limit")

        closed = fetch_closed_orders(trade_limit)
        if not closed:
            st.info("No closed trades found.")
        else:
            trade_rows = []
            for o in closed:
                trade_rows.append({
                    "Symbol":      o["symbol"],
                    "Side":        o["side"],
                    "Qty":         o["qty"],
                    "Fill Price":  f"${float(o['filled_avg_price']):,.2f}" if o["filled_avg_price"] else "—",
                    "Status":      o["status"],
                    "Filled At":   o["filled_at"][:19] if o["filled_at"] else "—",
                })
            st.dataframe(trade_rows, use_container_width=True, hide_index=True)

    render_recent_trades()

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
                "":             _STATUS_ICON.get(s["status"], ""),
                "Action":       f"{_ACTION_ICON.get(s['action'], '')} {s['action'].upper()}",
                "Ticker":       s["ticker"],
                "Theme":        s["theme"],
                "Confidence":   f"{s['confidence']:.2f}",
                "Status":       s["status"],
                "Skip Reason":  s.get("skip_reason") or "",
                "Created":      s["created_at"][:19] if s["created_at"] else "",
                "Executed":     s["executed_at"][:19] if s["executed_at"] else "—",
                "Rationale":    s["rationale"],
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)


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
        st.dataframe(rows, use_container_width=True, hide_index=True)


with tab_signals:
    render_signals_tab()

with tab_news:
    render_news_tab()

# ── Audit ─────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def fetch_audit_metrics(hours: int) -> dict:
    return compute_metrics(get_db(), hours=hours)


with tab_audit:
    col_ah1, col_ah2 = st.columns([3, 1])
    with col_ah1:
        st.subheader("Audit Report")
    with col_ah2:
        audit_hours = st.selectbox("Window", [6, 12, 24, 48], index=2, key="audit_hours")

    with st.spinner("Computing metrics…"):
        audit = fetch_audit_metrics(audit_hours)

    sigs = audit["signals"]
    pipeline = audit["pipeline"]
    themes = audit["themes"]
    pnl = audit["pnl_by_theme"]
    anomalies = audit["anomalies"]

    # Top-line signal metrics
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Signals (total)",    sigs["total"])
    a2.metric("Executed",           sigs["executed"])
    a3.metric("Skipped",            sigs["skipped"])
    a4.metric("Skip Rate",          f"{sigs['skip_rate']:.0%}")

    # Anomalies
    if anomalies:
        st.subheader("Anomalies")
        for a in anomalies:
            st.warning(a)
    else:
        st.success("No anomalies detected.")

    # Per-theme breakdown
    if themes:
        st.subheader("Signal Quality by Theme")
        theme_rows = []
        for theme, data in sorted(themes.items(), key=lambda x: -x[1]["total"]):
            skip_r = data.get("skip_reasons", {})
            skip_r_str = ", ".join(
                f"{k}:{v}"
                for k, v in sorted(skip_r.items(), key=lambda x: -x[1])
            ) if skip_r else "—"
            theme_rows.append({
                "Theme":        theme,
                "Total":        data["total"],
                "Executed":     data["executed"],
                "Skipped":      data["skipped"],
                "Skip Rate":    f"{data['skip_rate']:.0%}",
                "Avg Conf":     f"{data['avg_confidence']:.3f}",
                "Skip Reasons": skip_r_str,
            })
        st.dataframe(theme_rows, use_container_width=True, hide_index=True)

    # Pipeline health
    st.subheader("Pipeline Health")
    p1, p2, p3 = st.columns(3)
    p1.metric("Articles ingested",    pipeline["total_articles"])
    p2.metric("Articles per signal",  pipeline["articles_per_signal"])
    p3.metric("Sources active",       len(pipeline["by_source"]))

    if pipeline["by_source"]:
        source_rows = [
            {"Source": src, "Articles": cnt}
            for src, cnt in sorted(pipeline["by_source"].items(), key=lambda x: -x[1])
        ]
        st.dataframe(source_rows, use_container_width=True, hide_index=True)

    # P&L by theme
    if pnl:
        st.subheader("Trade P&L by Theme")
        pnl_rows = []
        for theme, data in sorted(pnl.items(), key=lambda x: -x[1]["count"]):
            sign = "+" if data["avg_return_pct"] >= 0 else ""
            pnl_rows.append({
                "Theme":       theme,
                "Trades":      data["count"],
                "Win Rate":    f"{data['win_rate']:.0%}",
                "Avg Return":  f"{sign}{data['avg_return_pct']:.2f}%",
            })
        st.dataframe(pnl_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No closed trades with fill and exit prices recorded yet.")
