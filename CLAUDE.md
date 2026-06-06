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

1. **Data Ingestion**: Finnhub API, RSS feeds (CNBC, Sky News, NPR, The Guardian)
2. **NLP/Sentiment**: FinBERT (`ProsusAI/finbert`) for sentiment **via ONNX Runtime (torch-free at runtime)**, spaCy for NER, keyword-based topic classification; broad pre-filter keywords pass articles to FinBERT, conviction threshold (0.4) handles false positives
3. **Signal Generation**: Rule-based event→trade mapping with confidence scoring (17 themes)
4. **Execution**: Alpaca (equities), OANDA (forex + commodities)
5. **Risk Management**: Position sizing (quarter-Kelly + ATR), circuit breakers, time-based stops
6. **Monitoring**: Telegram alerts (preferred), Streamlit dashboard, structured logging; FRED indicators fetched concurrently (`ThreadPoolExecutor(max_workers=6)`); dashboard uses staggered cache TTLs (45s/60s/90s/120s) to prevent synchronized expiration storms

## Project Structure

```
news-trading-bot/
├── CLAUDE.md                    # This file
├── README.md                    # Setup and usage docs
├── .env                         # API keys (NEVER committed to git)
├── .gitignore
├── .dockerignore
├── requirements.txt             # Runtime deps (torch-free; onnxruntime, not torch)
├── pyproject.toml               # Project metadata + tool config (pytest markers, etc.)
├── Dockerfile                   # Multi-stage: stage 1 exports FinBERT→ONNX with torch; stage 2 runtime is torch-free
├── docker-compose.yml           # Local multi-container dev setup
├── fly.toml                     # Fly.io deployment config
├── config/
│   └── settings.py              # Loads .env, defines all thresholds + risk limits
├── core/                        # Core pipeline modules (flat, not nested)
│   ├── alerts.py                # Telegram signal + exit notifications
│   ├── auditor.py               # Audit metrics engine (signals, pipeline health, P&L, anomalies)
│   ├── backtester.py            # Walk-forward backtest engine (yfinance)
│   ├── broker.py                # Alpaca wrapper (account, positions, orders)
│   ├── db.py                    # SQLite schema + repository; indexes on signals.created_at, signals.status, articles.fetched_at
│   ├── dedup.py                 # Jaccard headline similarity deduplication
│   ├── exit_manager.py          # Trailing stops + time-based exits
│   ├── forex.py                 # OANDA wrapper (forex + commodities)
│   ├── macro.py                 # FRED wrapper (key indicators, series); get_key_indicators() fetches all 13 concurrently via ThreadPoolExecutor(max_workers=6)
│   ├── macro_context.py         # Regime-aware signal confidence adjustment
│   ├── news.py                  # Finnhub wrapper (general + company news)
│   ├── risk_manager.py          # Position sizing, daily loss limit, trade cap
│   ├── rss.py                   # Concurrent RSS feed fetcher (CNBC, Sky News, NPR, Guardian)
│   ├── scheduler.py             # APScheduler polling loop (full pipeline)
│   ├── sentiment.py             # FinBERT sentiment scoring via ONNX Runtime (torch-free; model baked into image as ONNX by Dockerfile)
│   └── signal_gen.py            # Rule-based event→trade engine (17 themes); broad pre-filter keywords, FinBERT+conviction threshold for false positives
├── dashboard/
│   └── app.py                   # Streamlit monitoring dashboard; Broker/Macro/Forex clients initialized concurrently on cold start; selective refresh ("Refresh" skips 1hr FRED cache, "Refresh All" clears everything); staggered TTLs per data type
├── scripts/
│   ├── backtest.py              # Walk-forward backtest CLI
│   ├── fetch_logs.py            # Fetch Fly.io logs → logs/fly_YYYY-MM-DD_HH-MM.txt (NOTE: -n flag broken with current flyctl; use flyctl logs directly)
│   ├── fly_diag.sh              # Fly.io diagnostics helper (machine status, image hash, memory)
│   ├── reset_bot.py             # Full reset (--yes) or pending-queue drain (--drain-pending); cancels/closes broker positions, wipes SQLite
│   ├── run_audit.py             # Run audit engine against live DB via flyctl ssh console
│   ├── run_bot.py               # Main bot entry point
│   ├── start.sh                 # Docker startup script (bot + dashboard)
│   └── test_alert.py            # One-off Telegram alert smoke test
├── tests/                       # Mirrors core/ — one test module per core module
│   ├── conftest.py              # Shared fixtures
│   ├── test_alerts.py
│   ├── test_backtester.py
│   ├── test_broker.py
│   ├── test_connectivity.py     # Integration smoke tests (Finnhub, FRED, Alpaca)
│   ├── test_db.py
│   ├── test_dedup.py
│   ├── test_exit_manager.py
│   ├── test_forex.py
│   ├── test_macro_context.py
│   ├── test_risk_manager.py
│   ├── test_rss.py
│   ├── test_scheduler.py
│   ├── test_sentiment.py
│   ├── test_settings.py
│   └── test_signal_gen.py
└── data/                        # SQLite DB (gitignored)
```

## Tech Stack

| Component         | Tool / Library                          | Version   |
|-------------------|-----------------------------------------|-----------|
| Language          | Python                                  | 3.12+     |
| Sentiment runtime | `onnxruntime` (CPU) + `tokenizers`     | 1.26+     |
| Sentiment model   | `ProsusAI/finbert` exported to ONNX     | —         |
| NER               | `spacy` + `en_core_web_sm`             | 3.8+      |
| News API          | `finnhub-python`                        | 2.4+      |
| RSS Parsing       | `feedparser`                            | 6.0+      |
| Macro Data        | `fredapi`                               | 0.5+      |
| Market Data       | `yfinance`                              | 1.2+      |
| Equity Broker     | `alpaca-py`                             | 0.26+     |
| Forex Broker      | `oandapyV20`                            | 0.6+      |
| Scheduling        | `apscheduler`                           | 3.11+     |
| Database          | SQLite (MVP) → PostgreSQL (scale)       | —         |
| ONNX export (build-time only) | `torch` + `optimum[onnxruntime]` | torch 2.10 |
| HTTP              | `requests`                              | 2.32+     |
| Env Management    | `python-dotenv`                         | —         |

> **Runtime is torch-free.** `torch` and `optimum` live only in the Dockerfile's
> export stage, which converts `ProsusAI/finbert` to ONNX. The runtime image runs
> the model through `onnxruntime` (CPU) — libtorch (~227 MB RSS) never loads,
> which is what lets the Fly VM sit at 1 GB. The fp32 ONNX export is numerically
> identical to the torch pipeline (labels and scores match).

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

| Source                          | What It Provides                  | Cost  | Rate Limit       |
|---------------------------------|-----------------------------------|-------|-------------------|
| Finnhub                         | Financial news, market data       | Free  | 60 req/min        |
| RSS (CNBC, Sky News, NPR, Guardian) | Macro + geopolitical headlines | Free  | No limit          |
| FRED                            | 800K+ economic time series        | Free  | 120 req/min       |
| yfinance                        | Stock/commodity/forex prices      | Free  | Unofficial        |

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
- [x] More event→trade rules: forex pairs (EUR/USD), gold (GLD ETF), oil (BNO ETF) — commodities route to Alpaca, OANDA practice accounts don't allow CFDs
- [x] News deduplication — Jaccard similarity across sources (`core/dedup.py`)
- [x] Streamlit monitoring dashboard (`dashboard/app.py`)
- [x] Risk controls — position sizing, daily loss limit (`core/risk_manager.py`)
- [x] Macro context filter — FRED-based regime-aware confidence adjustment (`core/macro_context.py`)
- [x] Concurrent news fetching — ThreadPoolExecutor in scheduler + RSS client
- [x] RSS feeds — CNBC, Sky News, NPR, The Guardian (`core/rss.py`)

### Phase 3 — Harden & Validate ✅ COMPLETE
- [x] Walk-forward backtesting (`core/backtester.py` + `scripts/backtest.py`)
- [ ] Multi-source signal confirmation (dedup implemented; multi-source voting not yet)
- [x] Trailing stops and time-based exits (`core/exit_manager.py`)
- [x] Async news fetching (ThreadPoolExecutor in `core/scheduler.py` and `core/rss.py`)
- [x] Dockerize the application (`Dockerfile`, `docker-compose.yml`, `scripts/start.sh`)
- [x] Structured logging + auto-restart (Python `logging` throughout; `restart: unless-stopped` in compose)

### Phase 4 — Go Live ← CURRENT PHASE
- [x] Deploy to Fly.io (switched from Oracle Cloud — free tier, simpler ops) (`fly.toml`)
- [x] Confirm Fly.io deployment health (bot running, Telegram alerts firing, OANDA exits working)
- [x] Audit engine + runner (`core/auditor.py` + `scripts/run_audit.py`)
- [x] Broaden signal pre-filter keywords so FinBERT sees relevant articles (was dropping 100%)
- [x] **Signal cooldown** — suppress duplicate (ticker, action, theme) signals within 30min (`SIGNAL_COOLDOWN_MINUTES`); pending-signal expiry sweep every 5min
- [x] **OANDA pre-flight + V20 error capture** — cache account's tradeable instruments at startup; persist actual `errorCode`/`rejectReason` as `skip_reason` (no more bare "order_submission_failed")
- [x] **Equity SELL suppression** — drop SELL signals on equity tickers when no long position is held (replaces ~80 dead `no_position_to_sell` skips/wk with cleaner pre-flight)
- [x] **Commodity routing → Alpaca ETFs** — GLD for gold themes, BNO for Brent oil (OANDA practice doesn't offer CFDs)
- [x] **Fly.io RAM right-sized 2GB → 1.5GB** — measured live: bot peak RSS 867MB, dashboard 48MB, system ~73MB; 467MB MemAvailable headroom. Cost: ~$12 → ~$9.50/mo (≈21% saving)
- [x] **Torch-free FinBERT via ONNX Runtime** — export `ProsusAI/finbert` to ONNX in a Dockerfile build stage; runtime never installs torch, cutting bot RSS ~227MB. Enabled the further VM drop **1.5GB → 1GB** (`memory = '1024mb'` in `fly.toml`)
- [ ] Per-stage pipeline observability (`[PIPELINE]` log line per poll)
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
- **Staggered dashboard TTLs** — cache expiry times are intentionally offset per data type (45s signals/articles, 60s broker, 90s forex, 120s FRED macro) so refreshes never all fire at once; "Refresh" preserves the expensive 1hr FRED cache while "Refresh All" clears everything
- **Broad pre-filter + tight conviction threshold** — signal rule keywords are intentionally wide (e.g. "gold", "oil", "federal reserve") so real headlines pass through to FinBERT; the 0.4 conviction threshold and rule `actions` map handle false positives downstream
- **Signal cooldown** — `(ticker, action, theme)` tuple cooldown (default 30min) suppresses duplicate signals from distinct headlines covering the same event (e.g. multiple Reuters wires about Iran war producing repeated SPY/sell signals). Lookback includes `pending`, `executed`, AND prior cooldown rows to prevent sliding-window resurrection. Configurable via `SIGNAL_COOLDOWN_ENABLED` / `SIGNAL_COOLDOWN_MINUTES`
- **Commodities via Alpaca ETFs, not OANDA** — OANDA practice accounts don't permit commodity CFDs (XAU_USD, BCO_USD return INSTRUMENT_NOT_TRADEABLE). Gold themes route to `GLD`, oil themes to `BNO` — both trade on Alpaca alongside SPY. Trade-off: US market hours only, vs OANDA's 24/5
- **OANDA account pre-flight** — `ForexBroker._load_tradeable_instruments()` caches the account's tradeable list at startup; non-tradeable instruments skip with `instrument_not_enabled_for_account` instead of round-tripping a doomed order. Fail-open if the call errors
- **Equity SELL = position-gated** — SELL signals on equity tickers (SPY, GLD, BNO) require an existing long position. Without it the signal is suppressed at scheduler filter as `no_position_to_sell_suppressed`. Forex SELL is unaffected (native shorting)

## Skip Reasons (audit vocabulary)

Auditor groups signals by `skip_reason`. Common values, in roughly the order they appear in `_poll()`:

| Skip reason | Source | Meaning |
|---|---|---|
| `cooldown_active` | scheduler cooldown filter | Suppressed because a matching signal fired within `SIGNAL_COOLDOWN_MINUTES` |
| `no_position_to_sell_suppressed` | scheduler pre-flight | Equity SELL with no long position to close |
| `oanda_not_configured` | scheduler | Forex signal but OANDA env vars missing |
| `Daily trade limit reached (X/Y)` | risk_manager | `MAX_TRADES_PER_DAY` cap hit for the day |
| `Already hold a position in X` | risk_manager | Per-ticker BUY accumulation guard |
| `position_sizing_failed` | scheduler | Risk manager couldn't compute a non-zero qty |
| `no_position_to_sell` | scheduler (legacy) | Execute-time guard; should be rare now that pre-flight suppression exists |
| `order_submission_failed:<reason>` | scheduler + broker | Broker rejected the order. Suffix is e.g. `instrument_not_enabled_for_account`, `INSTRUMENT_NOT_TRADEABLE` (OANDA errorCode), `MARKET_HALTED`, `INSUFFICIENT_MARGIN` |
| `pending_timeout` | expire_pending_signals job | Pending signal aged past `PENDING_SIGNAL_EXPIRY_MINUTES` |
| `cooldown_backfill` | `reset_bot.py --drain-pending` | One-shot expiry at deploy time |

## Risk Management Rules

- Max 2–5% of portfolio per position
- 3% daily loss → pause until next session
- 7% weekly loss → pause until next week
- 15% max drawdown → require manual reset
- Time-based exits: close positions after 2–4 hours if thesis isn't working
- Minimum confidence threshold of 0.4 (configurable via `SIGNAL_CONVICTION_THRESHOLD`)
- Multi-source confirmation: `MIN_SOURCE_COUNT` defaults to 1 for paper trading; **set to 2 via env var for production** to require independent corroboration before executing
- Signal cooldown: `SIGNAL_COOLDOWN_MINUTES` (default 30); `PENDING_SIGNAL_EXPIRY_MINUTES` (default 60). Disable with `SIGNAL_COOLDOWN_ENABLED=false` for instant rollback without redeploy
- Staggered dashboard cache TTLs are configured in `dashboard/app.py` (45s signals, 60s broker, 90s forex, 120s FRED)

## Full Bot Reset (Fresh Paper Trading)

Use this when you want to wipe all history and start clean — e.g. after a major strategy change or to reset performance tracking.

### Step 1 — Create a new Alpaca paper account

Alpaca no longer supports in-place balance resets. You must create a new paper account:

1. Log in at https://app.alpaca.markets
2. Switch to Paper Trading, then create a new paper account
3. Copy the new **API Key** and **Secret Key** from the new account

### Step 2 — Update Fly.io secrets with the new Alpaca keys

```bash
flyctl secrets set ALPACA_API_KEY=<new-key> ALPACA_SECRET_KEY=<new-secret> -a trading-bot-lingering-lake-4314
```

This triggers an automatic redeploy. Wait for the app to come back up before continuing.

### Step 3 — Wipe the SQLite database and close any open broker positions

```bash
flyctl ssh console -a trading-bot-lingering-lake-4314 --command "python /app/scripts/reset_bot.py --yes"
```

This will:
- Cancel all open Alpaca orders
- Close all open Alpaca positions
- Close all open OANDA positions (if configured)
- Clear the SQLite DB (articles, signals, bot_state tables reset to empty)

### Step 4 — Verify

```bash
flyctl logs -a trading-bot-lingering-lake-4314
```

Look for the scheduler starting up and news polling beginning without errors. The dashboard at `https://trading-bot-lingering-lake-4314.fly.dev` should show empty tables — that confirms a clean slate. No bot restart is needed; the scheduler picks up fresh data on its next poll cycle (within 5 minutes).

## Fly.io Deployment Gotchas

Two failure modes observed when deploying via GitHub Actions or `flyctl deploy --remote-only`:

1. **Silent auto-revert when image exceeds 8GB unpacked.** Fly's deploy log reports "Machine ... is now in a good state" even when the new image was rolled back to the prior one (the *reverted* machine is what reached good state). Check by comparing `flyctl status` Image hash against the deploy log. Historically the bloat was torch in the runtime image. As of the ONNX migration, **torch now lives only in the Dockerfile's export stage** (`torch==2.10.0`, pinned to the CPU wheel) and the runtime image is torch-free — so the runtime image is far smaller. Still verify the image hash after deploy; this gotcha hasn't been re-confirmed under the new multi-stage build.
2. **New machine stays `stopped` after rolling deploy** when the old machine is destroyed and a fresh one is launched in its place. `min_machines_running=1` doesn't seem to auto-start it. Run `flyctl machine start <id>` manually after verifying the deploy.

Always verify after deploy:
```bash
flyctl machine list -a trading-bot-lingering-lake-4314
flyctl ssh console -a trading-bot-lingering-lake-4314 --command "grep -c '<new-code-marker>' /app/<file>"
```

## Drain Pending Signals Only (Cooldown Backfill)

When a code change introduces new pre-flight filters (cooldown, position suppression), the existing pending queue may contain signals that should have been suppressed. Drain them with one shot — no broker reset, no DB wipe:

```bash
flyctl ssh console -a trading-bot-lingering-lake-4314 \
  --command "python /app/scripts/reset_bot.py --drain-pending --yes"
```

This marks all `status='pending'` rows as `expired` with `skip_reason='cooldown_backfill'`. Run immediately after deploying a filter change; safe to re-run (no-op if the queue is already drained).

---

## Log Review Process

### How to Access Fly.io Logs

The app (`trading-bot-lingering-lake-4314`) writes all output to stdout. Fly.io captures it automatically and retains ~24–48 hours of history.

**Quick access (terminal):**
```bash
# Live tail (recommended — -n flag is broken in current flyctl)
flyctl logs --app trading-bot-lingering-lake-4314

# Filter for errors inline (pipe from live tail, Ctrl-C when done)
flyctl logs --app trading-bot-lingering-lake-4314 | grep ERROR
```

> **Note:** `flyctl logs -n <N>` is broken in current flyctl versions (`unknown command "N"`). Use the live tail and copy output manually, or use `fetch_logs.py` which wraps the same command (also broken until flyctl is fixed).

**Audit report (queries DB directly — more reliable than log scraping):**
```bash
flyctl ssh console -a trading-bot-lingering-lake-4314 --command "python /app/scripts/run_audit.py"
flyctl ssh console -a trading-bot-lingering-lake-4314 --command "python /app/scripts/run_audit.py --hours 48"
```

### Structured Log Markers

Key events are tagged so you can grep them instantly:

| Marker | Where | Meaning |
|--------|-------|---------|
| `[SIGNAL]` | `core/signal_gen.py` | A trading signal was generated |
| `[ORDER]` | `core/broker.py`, `core/forex.py` | An order was submitted, filled, rejected, or closed |
| `[RISK]` | `core/risk_manager.py` | A risk limit fired (daily loss, trade cap) |
| `[COOLDOWN]` | `core/scheduler.py` | Duplicate signal suppressed within `SIGNAL_COOLDOWN_MINUTES` |
| `[POSITION]` | `core/scheduler.py` | Equity SELL suppressed because no long position is held |
| `ERROR` | All modules | Unexpected exception — investigate immediately |
| `WARNING` | All modules | Degraded operation — worth reviewing |

### Audit Report (preferred)

Queries the live SQLite DB — more structured and reliable than log scraping:

```bash
flyctl ssh console -a trading-bot-lingering-lake-4314 --command "python /app/scripts/run_audit.py"
```

Paste the output to Claude Code for review. The report covers signals, skip rates, pipeline health by source, P&L by theme, and anomaly detection.

### Claude Code Review Workflow (log-based)

1. **Tail** the latest logs:
   ```bash
   flyctl logs --app trading-bot-lingering-lake-4314
   ```
2. **Paste output** to Claude Code for review
3. **Drill down** with follow-up questions:
   > "Show me all [RISK] events in that file and explain what triggered each one"
   > "Were there any [SIGNAL] lines that did not produce a matching [ORDER]? Why not?"
4. **Iterate** — Claude Code uses `Read` and `Grep` on the log file to answer precisely.

### Log Retention

Fly.io only keeps ~24–48 hours natively. Run `fetch_logs.py` at least once per day to build a local archive in `logs/` (gitignored). For longer-term retention, consider shipping logs to a free tier of Papertrail or Logtail via a Fly.io log shipper.

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
