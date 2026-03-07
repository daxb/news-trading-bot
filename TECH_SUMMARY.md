# Technical Implementation Summary
## News-Driven Macro Trading Bot

**Last updated:** 2026-03-07 | **Status:** Phase 4 — Deployed to Fly.io

---

## 1. System Overview

The bot ingests macro-economic and geopolitical news, scores it with FinBERT, maps high-confidence sentiment to trading signals, and executes market orders via Alpaca (equities) and OANDA (forex/commodities). It targets medium-frequency strategies (minutes to hours) — not HFT.

**Pipeline:**

```
News Sources → Dedup/Filter → FinBERT Sentiment → Signal Rules → Risk Checks → Broker Execution
                                                        ↓
                                               Macro Context (FRED)
```

**Polling interval:** 5 minutes (configurable via `NEWS_POLL_INTERVAL_SECONDS`).
**Position monitor:** every 2 minutes for trailing stops and time-based exits.

---

## 2. Key Components

| Module | What It Does |
|---|---|
| `core/scheduler.py` | APScheduler loop; wires the full pipeline; runs initial poll on start |
| `core/news.py` | Finnhub general + company news fetcher; normalized article schema |
| `core/rss.py` | Concurrent RSS fetcher (BBC, CNBC, MarketWatch, Yahoo Finance) |
| `core/dedup.py` | Two-pass dedup: DB ID check, then Jaccard headline similarity |
| `core/sentiment.py` | FinBERT wrapper (`ProsusAI/finbert`); outputs label + confidence score |
| `core/signal_gen.py` | Priority rule table (17 themes); keyword match → action mapping |
| `core/macro_context.py` | FRED-based regime filter; adjusts signal confidence by macro state |
| `core/risk_manager.py` | Trade count cap, daily loss limit, percent-of-equity position sizing |
| `core/exit_manager.py` | Trailing stops and time-based exits (default: 4-hour max hold) |
| `core/broker.py` | Alpaca paper/live wrapper (account, positions, orders, portfolio history) |
| `core/forex.py` | OANDA wrapper; forex and commodities (EUR/USD, XAU/USD, BCO/USD) |
| `core/db.py` | SQLite repository; stores articles, signals, execution status |
| `core/alerts.py` | Telegram signal alerts, hourly P&L digest (09:30–16:00 ET), and open orders summary |
| `core/auditor.py` | 24-hour metrics (signals, themes, P&L) and anomaly detection (6 checks) |
| `config/settings.py` | All config loaded from `.env`; no hardcoded values anywhere else |
| `dashboard/app.py` | Streamlit dashboard: signals, positions, open orders, portfolio value + return % charts (1D/1W/1M/3M/1Y) |

---

## 3. Tech Stack

| Component | Tool | Notes |
|---|---|---|
| Language | Python 3.12+ | Type hints throughout |
| Sentiment | `transformers` + `ProsusAI/finbert` | ~440 MB download on first run |
| NER | `spacy` + `en_core_web_sm` | Named entity recognition |
| Scheduling | `apscheduler` 3.11+ | BackgroundScheduler; daemon thread |
| Equity broker | `alpaca-py` 0.26+ | Paper trading default |
| Forex broker | `oandapyV20` | Optional; gracefully skipped if keys absent |
| Macro data | `fredapi` | Refreshes every 12 poll cycles (~1 hr) |
| Market data | `yfinance` | Backtesting and price lookups |
| Database | SQLite (MVP) | `data/trading.db`; gitignored |
| News APIs | Finnhub, RSS feeds | Fetched concurrently via `ThreadPoolExecutor` |
| Alerts | Telegram Bot API | Signal notifications + hourly digest |
| Dashboard | Streamlit | Co-deployed in Docker image |
| Deployment | Fly.io | Single `fly.toml`; Docker-based |
| Env management | `python-dotenv` | All secrets in `.env` |

---

## 4. Data Flow

**Each poll cycle (every 5 minutes):**

1. **Fetch** — Finnhub and all RSS feeds are called concurrently. Raw articles are merged into a single list.

2. **Dedup** — First, DB ID check drops already-seen articles. Second, Jaccard similarity dedup (`DEDUP_SIMILARITY_THRESHOLD=0.5`, 4-hour window) drops cross-source near-duplicates.

3. **Pre-filter** — `SignalGenerator.is_relevant()` runs a cheap keyword scan. Articles that match no rule keywords are dropped before hitting FinBERT. This avoids wasting ~2 s/article on dividend listicles.

4. **Cap** — Batch is capped at 50 articles (`MAX_ARTICLES_PER_CYCLE`). At ~2 s/article on CPU, 50 articles = ~100 s, which fits inside the 300 s poll window.

5. **Score** — `SentimentAnalyzer.score_articles()` runs each article through FinBERT (truncated to 512 tokens). Returns `sentiment_label` (positive/negative/neutral) and `sentiment_score` (0.0–1.0).

6. **Signal generation** — `SignalGenerator.generate_signals()` applies the priority rule table. First matching rule wins. Confidence = `sentiment_score × rule.confidence_mult`. Signals below `SIGNAL_CONVICTION_THRESHOLD` (default 0.4) are dropped.

7. **Macro context adjustment** — `MacroContext.adjust_signals()` scales confidence up or down based on 14 FRED indicators across four categories: *Policy* (fed funds rate), *Growth/Labour* (unemployment, jobless claims, consumer sentiment), *Rates/Spreads* (10Y–2Y yield curve, HY credit spreads, 5Y inflation expectations), and *Risk/FX* (VIX, USD index). Twelve rules map these regime readings to confidence boosts or penalties per signal theme. FRED data refreshes every 12 cycles (~1 hr).

8. **Persist and execute** — Signals are saved to SQLite. For each signal, `RiskManager.can_trade()` is called. If approved, `position_qty()` sizes the position, and a market order is submitted to Alpaca or OANDA depending on the ticker format (`_` in ticker → forex).

9. **Alert** — Successful execution triggers a Telegram notification with ticker, action, quantity, and order ID.

**Separate position monitor (every 2 minutes):**
`ExitManager.check_exits()` scans open positions and closes any that have hit a trailing stop or exceeded `MAX_HOLD_HOURS` (default 4 hours).

---

## 5. Risk Management Rules

All limits are configurable via `.env`.

| Rule | Default | Implementation |
|---|---|---|
| Max position size | 5% of equity | `MAX_POSITION_PCT=0.05`; `RiskManager.position_qty()` |
| Max trades per day | 10 | `MAX_TRADES_PER_DAY=10`; checked in `can_trade()` |
| Daily loss limit | 5% | `MAX_DAILY_LOSS_PCT=0.05`; compares current vs session-start equity |
| Stop loss per trade | 2% | `STOP_LOSS_PCT=0.02`; enforced by `ExitManager` |
| Max hold time | 4 hours | `MAX_HOLD_HOURS=4.0`; time-based exit in `ExitManager` |
| Max theme exposure | 15% | `MAX_THEME_EXPOSURE_PCT=0.15` |
| Max total exposure | 60% | `MAX_TOTAL_EXPOSURE_PCT=0.60` |
| Min source count | 1 (paper) / 2 (production) | `MIN_SOURCE_COUNT`; corroboration within 4-hour window |
| Minimum confidence | 0.4 | `SIGNAL_CONVICTION_THRESHOLD=0.4`; drops low-quality signals |
| Equity-only short guard | — | Sell signals skipped if no existing position (equities only) |
| Paper trading gate | On by default | `PAPER_TRADING=true`; prints loud warning if disabled |

The `RiskManager` is stateful: session-start equity is captured at construction and used as the daily loss baseline. It resets on bot restart, which is acceptable for MVP.

---

## 6. Signal Rules (17 Themes)

Rules are priority-ordered. First match wins.

| Theme | Instrument | Confidence Mult |
|---|---|---|
| `fed_hawkish` | SPY | 1.00 |
| `fed_dovish` | SPY | 1.00 |
| `jobs_strong` | SPY | 0.90 |
| `inflation` | SPY | 0.85 |
| `recession_risk` | SPY | 0.85 |
| `geopolitical_risk` | SPY | 0.75 |
| `market_rally` | SPY | 0.65 |
| `usd_strength` | EUR_USD | 0.80 |
| `usd_weakness` | EUR_USD | 0.80 |
| `gold_safe_haven` | XAU_USD | 0.75 |
| `gold_selloff` | XAU_USD | 0.75 |
| `gold_inflation_hedge` | XAU_USD | 0.75 |
| `gold_geopolitical` | XAU_USD | 0.75 |
| `oil_demand_growth` | BCO_USD | 0.75 |
| `oil_supply_squeeze` | BCO_USD | 0.75 |
| `oil_oversupply` | BCO_USD | 0.75 |
| `oil_geopolitical` | BCO_USD | 0.75 |

The confidence multiplier reflects expected signal reliability — Fed policy rules get 1.0; momentum/market-rally gets 0.65 due to higher noise.

---

## 7. Deployment

**Docker** — single image bundles the bot and Streamlit dashboard. `scripts/start.sh` starts both. `docker-compose.yml` is available for local multi-container dev.

**Fly.io** — configured in `fly.toml`. The bot runs as a persistent process with `restart: unless-stopped` behavior. Structured Python `logging` writes to stdout, captured by Fly's log aggregator.

**Environment** — all secrets injected via `.env` (local) or Fly secrets (deployed). Required keys: `FINNHUB_API_KEY`, `FRED_API_KEY`, `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`. OANDA and Telegram keys are optional; their features degrade gracefully if absent.

**Current status:** Fly.io deployment exists (`fly.toml` committed). Dashboard reachability and live trading confirmation are the remaining Phase 4 items.

---

## 8. Observability & Alerts

### Audit System (`core/auditor.py`)

The auditor runs a 24-hour lookback on the SQLite database and computes:

- **Signal counts** — total signals generated, executed, and skipped
- **Per-theme breakdown** — signal volume and skip rate by theme
- **P&L by theme** — realized gain/loss attributed to each signal theme
- **Pipeline stats** — articles processed, dedup drop rate, pre-filter drop rate

Six anomaly checks run on each audit cycle:

| Check | Trigger Condition |
|---|---|
| High skip rate | ≥90% of all signals skipped (risk or confidence rejection) |
| Theme concentration | Single theme accounts for ≥60% of signals (diversification failure) |
| Missing feeds | One or more news sources returned zero articles |
| Position accumulation | ≥3 open positions in the same direction on the same instrument |
| Pipeline stall | No articles processed in the last 24 hours |
| Per-theme high skip | Any single theme has a ≥95% skip rate |

### Telegram Alerts (`core/alerts.py`)

| Alert Type | Trigger | Notes |
|---|---|---|
| Signal execution | Each executed trade | Ticker, action, quantity, order ID |
| Hourly digest | 09:30–16:00 ET, top of hour | Open positions, session P&L summary |
| Exit notification | Each position close | Reason (trailing stop or time-based), realized P&L |
| Daily audit | 16:10 ET | Full 24-hour metrics and any anomaly flags |
| Startup/shutdown | Bot start and graceful stop | Confirms pipeline is running or halted |

All Telegram alerts degrade gracefully: if `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID` are absent from the environment, alert calls are silently no-ops and the bot continues running normally.
