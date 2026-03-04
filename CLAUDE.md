# CLAUDE.md — News-Driven Geopolitical Trading Bot

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

1. **Data Ingestion**: Finnhub API, RSS feeds (BBC, AP), GDELT, Reddit `.json` endpoints
2. **NLP/Sentiment**: FinBERT (`ProsusAI/finbert`) for sentiment, spaCy for NER, keyword-based topic classification
3. **Signal Generation**: Rule-based event→trade mapping with confidence scoring
4. **Execution**: Alpaca (equities), OANDA (forex), IBKR (commodities/futures)
5. **Risk Management**: Position sizing (quarter-Kelly + ATR), circuit breakers, time-based stops
6. **Monitoring**: Telegram alerts, Streamlit dashboard, structured logging

## Project Structure

```
news-trading-bot/
├── CLAUDE.md                    # This file
├── .env                         # API keys (NEVER committed to git)
├── .gitignore
├── requirements.txt
├── config/
│   └── settings.py              # Loads .env, defines thresholds
├── src/
│   ├── ingestion/
│   │   ├── news_fetcher.py      # Finnhub + RSS + GDELT polling
│   │   └── price_fetcher.py     # yfinance / broker streaming
│   ├── nlp/
│   │   ├── sentiment.py         # FinBERT sentiment scoring
│   │   ├── preprocessor.py      # Text cleaning, deduplication
│   │   └── ner.py               # spaCy entity extraction
│   ├── strategy/
│   │   ├── signal_gen.py        # Event→trade rules engine
│   │   └── filters.py           # Confidence thresholds, confirmations
│   ├── execution/
│   │   ├── broker.py            # Unified broker interface
│   │   └── paper_trader.py      # Paper trading wrapper
│   ├── risk/
│   │   └── risk_manager.py      # Position sizing, circuit breakers
│   ├── monitoring/
│   │   ├── telegram_bot.py      # Trade alerts
│   │   └── dashboard.py         # Streamlit dashboard
│   └── db/
│       ├── models.py            # SQLite schema
│       └── repository.py        # DB read/write operations
├── scripts/
│   ├── run_bot.py               # Main entry point with APScheduler
│   └── backtest.py              # Historical strategy testing
├── tests/
└── data/                        # SQLite DB, CSV cache (gitignored)
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
| Equity Broker     | `alpaca-py`                             | (add later)|
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
| Reddit .json  | Subreddit sentiment (WSB, etc.)   | Free  | ~10 req/min       |
| FRED          | 800K+ economic time series        | Free  | 120 req/min       |
| yfinance      | Stock/commodity/forex prices      | Free  | Unofficial        |

## Phased Roadmap

### Phase 1 — MVP (Weeks 1–2) ← CURRENT PHASE
- [x] Project setup, GitHub repo, virtual environment
- [x] Install core dependencies
- [x] API key registration (Finnhub, FRED, Alpaca)
- [ ] `news_fetcher.py` — pull headlines from Finnhub + RSS
- [ ] SQLite storage for articles
- [ ] FinBERT sentiment scoring
- [ ] Basic rules engine (event → SPY paper trades)
- [ ] Alpaca paper trading integration
- [ ] APScheduler for automated polling
- [ ] Telegram alerts

### Phase 2 — Multi-Asset Expansion (Weeks 3–4)
- [ ] Add GDELT and Reddit `.json` for broader news coverage
- [ ] OANDA integration for forex paper trading
- [ ] More event→trade rules (forex pairs, gold, oil)
- [ ] News deduplication
- [ ] Streamlit monitoring dashboard
- [ ] Risk controls (max position size, daily loss limit)

### Phase 3 — Harden & Validate (Months 2–3)
- [ ] Walk-forward backtesting
- [ ] Multi-source signal confirmation
- [ ] Trailing stops and time-based exits
- [ ] Async news fetching
- [ ] Dockerize the application
- [ ] Structured logging + auto-restart

### Phase 4 — Go Live (Month 3+)
- [ ] Deploy to Oracle Cloud (free ARM instance)
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
- Reddit data: use public `.json` endpoints only, respect rate limits

## Conventions

- Python 3.12+ with type hints where practical
- Environment variables via `python-dotenv`
- All config in `config/settings.py`, no hardcoded keys or thresholds
- Logging via Python's `logging` module (not print statements)
- Snake_case for files/functions, PascalCase for classes
- Tests in `tests/` mirroring `src/` structure
