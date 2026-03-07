# CLAUDE.md — FIONA (Fast Inference On News Alpha)

## Project Overview

A Python trading bot that ingests macro-economic and geopolitical news, runs sentiment analysis via FinBERT, generates trading signals, and executes trades across equities, forex, and commodities. The system targets medium-frequency strategies (minutes to hours) driven by macro themes rather than millisecond-level reactions.

## Developer Profile

- **Skill level**: Intermediate Python (can follow guides, not expert-level)
- **OS**: macOS (Apple Silicon / M-series)
- **Editor**: VS Code
- **Source control**: GitHub (private repo)
- **Timeline**: MVP in weeks, minimal budget ($0/month target)

## Architecture

```
Data Ingestion → NLP/Sentiment → Signal Generation → Order Execution → Risk Management → Monitoring
```

### Pipeline Stages

1. **Data Ingestion**: Finnhub API, RSS feeds (BBC, AP), GDELT, NewsAPI (free tier)
2. **NLP/Sentiment**: FinBERT (`ProsusAI/finbert`) for sentiment, spaCy for NER, keyword-based topic classification
3. **Signal Generation**: Rule-based event→trade mapping with confidence scoring
4. **Execution**: Alpaca (equities), OANDA (forex), IBKR (commodities/futures)
5. **Risk Management**: Position sizing (quarter-Kelly + ATR), circuit breakers, time-based stops
6. **Monitoring**: Telegram alerts (preferred), Streamlit dashboard, structured logging

## Project Structure

```
news-trading-bot/
├── CLAUDE.md                    # This file
├── README.md                    # Setup and usage docs
├── .env                         # API keys (NEVER committed to git)
├── .gitignore
├── .dockerignore
├── requirements.txt
├── Dockerfile                   # Single-image build (bot + dashboard)
├── docker-compose.yml           # Local multi-container dev setup
├── fly.toml                     # Fly.io deployment config
├── config/
│   └── settings.py              # Loads .env, defines all thresholds + risk limits
├── core/                        # Core pipeline modules (flat, not nested)
│   ├── alerts.py                # Telegram signal + exit notifications
│   ├── backtester.py            # Walk-forward backtest engine (yfinance)
│   ├── broker.py                # Alpaca wrapper (account, positions, orders)
│   ├── db.py                    # SQLite schema + repository
│   ├── dedup.py                 # Jaccard headline similarity deduplication
│   ├── exit_manager.py          # Trailing stops + time-based exits
│   ├── forex.py                 # OANDA wrapper (forex + commodities)
│   ├── macro.py                 # FRED wrapper (key indicators, series)
│   ├── macro_context.py         # Regime-aware signal confidence adjustment
│   ├── news.py                  # Finnhub wrapper (general + company news)
│   ├── risk_manager.py          # Position sizing, daily loss limit, trade cap
│   ├── rss.py                   # Concurrent RSS feed fetcher
│   ├── scheduler.py             # APScheduler polling loop (full pipeline)
│   ├── sentiment.py             # FinBERT sentiment scoring
│   └── signal_gen.py            # Rule-based event→trade engine (17 themes)
├── dashboard/
│   └── app.py                   # Streamlit monitoring dashboard
├── scripts/
│   ├── backtest.py              # Walk-forward backtest CLI
│   ├── run_bot.py               # Main bot entry point
│   └── start.sh                 # Docker startup script (bot + dashboard)
├── tests/
│   ├── test_connectivity.py     # Integration smoke tests (Finnhub, FRED, Alpaca)
│   ├── test_db.py
│   ├── test_scheduler.py
│   ├── test_sentiment.py
│   └── test_signal_gen.py
└── data/                        # SQLite DB (gitignored)
```

## Tech Stack

| Component         | Tool / Library                          | Version   |
|-------------------|-----------------------------------------|-----------|
| Language          | Python                                  | 3.12+     |
| Sentiment         | `transformers` + `ProsusAI/finbert`    | 5.2+      |
| NER               | `spacy` + `en_core_web_sm`             | 3.8+      |
| News API          | `finnhub-python`                        | 2.4+      |
| RSS Parsing       | `feedparser`                            | 6.0+      |
| Macro Data        | `fredapi`                               | 0.5+      |
| Market Data       | `yfinance`                              | 1.2+      |
| Equity Broker     | `alpaca-py`                             | 0.26+     |
| Forex Broker      | `oandapyV20`                            | (add later)|
| Scheduling        | `apscheduler`                           | 3.11+     |
| Database          | SQLite (MVP) → PostgreSQL (scale)       | —         |
| ML Framework      | `torch`                                 | 2.10+     |
| HTTP              | `requests`                              | 2.32+     |
| Env Management    | `python-dotenv`                         | —         |

## API Keys & Environment

All secrets stored in `.env` (gitignored). Required keys:

```
FINNHUB_API_KEY=...      # finnhub.io (free, 60 req/min)
FRED_API_KEY=...         # fred.stlouisfed.org (free, 120 req/min)
ALPACA_API_KEY=...       # alpaca.markets (free paper trading)
ALPACA_SECRET_KEY=...    # alpaca.markets (paired with above)
```

Keys added later as the project expands:
```
OANDA_API_KEY=...        # Phase 2: forex
OANDA_ACCOUNT_ID=...     # Phase 2: forex
TELEGRAM_BOT_TOKEN=...   # Phase 2: alerts
TELEGRAM_CHAT_ID=...     # Phase 2: alerts
```

## Data Sources

| Source         | What It Provides                  | Cost  | Rate Limit       |
|---------------|-----------------------------------|-------|-------------------|
| Finnhub       | Financial news, market data       | Free  | 60 req/min        |
| RSS (BBC, AP) | Geopolitical headlines            | Free  | No limit          |
| GDELT         | Global event database             | Free  | No key needed     |
| NewsAPI       | Broad English-language news       | Free  | 100 req/day       |
| FRED          | 800K+ economic time series        | Free  | 120 req/min       |
| yfinance      | Stock/commodity/forex prices      | Free  | Unofficial        |

## Phased Roadmap

### Phase 1 — MVP ✅ COMPLETE
- [x] Project setup, GitHub repo, virtual environment
- [x] Install core dependencies (finnhub, fredapi, alpaca-py, dotenv)
- [x] API key registration (Finnhub, FRED, Alpaca)
- [x] `core/news.py` — Finnhub general + company news, normalized schema
- [x] `core/macro.py` — FRED key indicators + series fetching
- [x] `core/broker.py` — Alpaca paper trading (account, positions, orders)
- [x] `config/settings.py` — env loading, risk thresholds, paper trading gate
- [x] `tests/test_connectivity.py` — integration smoke tests for all APIs
- [x] SQLite storage for articles and signals (`core/db.py`)
- [x] FinBERT sentiment scoring (`core/sentiment.py`)
- [x] Basic rules engine (event → SPY paper trades) (`core/signal_gen.py`)
- [x] APScheduler polling loop (`core/scheduler.py` + `scripts/run_bot.py`)
- [x] Telegram alerts (`core/alerts.py` — signal + exit notifications)

### Phase 2 — Multi-Asset Expansion ✅ COMPLETE
- [ ] Add GDELT and NewsAPI for broader news coverage (Reddit removed — paid API, sarcasm/noise issues)
- [x] OANDA integration for forex paper trading (`core/forex.py`)
- [x] More event→trade rules: forex pairs (EUR/USD), gold (XAU/USD), oil (BCO/USD)
- [x] News deduplication — Jaccard similarity across sources (`core/dedup.py`)
- [x] Streamlit monitoring dashboard (`dashboard/app.py`)
- [x] Risk controls — position sizing, daily loss limit (`core/risk_manager.py`)
- [x] Macro context filter — FRED-based regime-aware confidence adjustment (`core/macro_context.py`)
- [x] Concurrent news fetching — ThreadPoolExecutor in scheduler + RSS client
- [x] RSS feeds — BBC, CNBC, MarketWatch, Yahoo Finance (`core/rss.py`)

### Phase 3 — Harden & Validate ✅ COMPLETE
- [x] Walk-forward backtesting (`core/backtester.py` + `scripts/backtest.py`)
- [ ] Multi-source signal confirmation (dedup implemented; multi-source voting not yet)
- [x] Trailing stops and time-based exits (`core/exit_manager.py`)
- [x] Async news fetching (ThreadPoolExecutor in `core/scheduler.py` and `core/rss.py`)
- [x] Dockerize the application (`Dockerfile`, `docker-compose.yml`, `scripts/start.sh`)
- [x] Structured logging + auto-restart (Python `logging` throughout; `restart: unless-stopped` in compose)

### Phase 4 — Go Live ← CURRENT PHASE
- [x] Deploy to Fly.io (switched from Oracle Cloud — free tier, simpler ops) (`fly.toml`)
- [ ] Confirm Fly.io deployment health (dashboard reachable, bot running)
- [ ] Live trading with minimum capital ($500–2,000)
- [ ] Parallel paper trading for comparison
- [ ] ML-based signal refinement (gradient boosting)

## Key Design Decisions

- **Rule-based signals for MVP** — transparent, debuggable, no training data needed
- **FinBERT over VADER** — 97% vs ~50% accuracy on financial text
- **APScheduler over Celery** — simpler, no Redis dependency for MVP
- **SQLite for MVP** — zero setup; migrate to PostgreSQL when needed
- **2–5 minute polling intervals** — news strategies don't need sub-second latency
- **Quarter-Kelly position sizing** — mathematically sound but conservative
- **Multi-source confirmation** — never trade on a single headline

## Risk Management Rules

- Max 2–5% of portfolio per position
- 3% daily loss → pause until next session
- 7% weekly loss → pause until next week
- 15% max drawdown → require manual reset
- Time-based exits: close positions after 2–4 hours if thesis isn't working
- Minimum confidence threshold of 0.5 to execute any trade
- Require 2+ independent news sources before trading

## Legal Notes

- No registration needed for personal algo trading (SEC/FINRA)
- Pattern Day Trader rule: 4+ day trades in 5 days → $25K equity required (equities only)
- Consider Section 475(f) Mark-to-Market election for tax purposes
- Wash sale rule is a major trap for algo traders — track carefully

## Conventions

- Python 3.12+ with type hints where practical
- Environment variables via `python-dotenv`
- All config in `config/settings.py`, no hardcoded keys or thresholds
- Logging via Python's `logging` module (not print statements)
- Snake_case for files/functions, PascalCase for classes
- Tests in `tests/` mirroring `core/` structure
