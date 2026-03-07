# FIONA — Fast Inference On News Alpha

A news-driven algorithmic trading bot that ingests macro-economic and geopolitical news, scores it with FinBERT sentiment analysis, and executes paper trades across equities (Alpaca), forex (OANDA), and commodities.

## How It Works

```
News (Finnhub + RSS) → FinBERT Sentiment → Rules Engine → Macro Filter → Risk Manager → Broker
```

Every 5 minutes the bot:
1. Fetches headlines from Finnhub and 5 RSS feeds (BBC World, BBC Business, CNBC, AP Top News, AP Business) concurrently
2. Deduplicates by article ID and Jaccard headline similarity
3. Scores each article with FinBERT (`ProsusAI/finbert`)
4. Matches headlines against a priority rule table to generate signals (SPY, EUR/USD, XAU/USD, BCO/USD)
5. Adjusts signal confidence using live FRED macro indicators (Fed rate, unemployment, 10-yr yield)
6. Runs risk checks (daily loss limit, trade count cap, position sizing)
7. Executes approved signals via Alpaca (equities) or OANDA (forex/commodities)
8. Sends Telegram alerts on execution

A separate job runs every 2 minutes to check for trailing-stop or time-based exit conditions on open positions.

## Project Structure

```
news-trading-bot/
├── config/
│   └── settings.py          # All config loaded from .env
├── core/
│   ├── alerts.py            # Telegram notifications
│   ├── auditor.py           # Daily audit metrics + anomaly detection
│   ├── backtester.py        # Walk-forward backtest engine (yfinance)
│   ├── broker.py            # Alpaca paper/live trading wrapper
│   ├── db.py                # SQLite repository (articles + signals)
│   ├── dedup.py             # Jaccard headline deduplication
│   ├── exit_manager.py      # Trailing stops + time-based exits
│   ├── forex.py             # OANDA forex/commodities wrapper
│   ├── macro.py             # FRED macro data wrapper
│   ├── macro_context.py     # Regime-aware confidence adjustment
│   ├── news.py              # Finnhub news wrapper
│   ├── risk_manager.py      # Daily loss limit + position sizing
│   ├── rss.py               # Concurrent RSS feed fetcher
│   ├── scheduler.py         # APScheduler polling loop (main pipeline)
│   ├── sentiment.py         # FinBERT sentiment scorer
│   └── signal_gen.py        # Rule-based event → trade engine
├── dashboard/
│   └── app.py               # Streamlit monitoring dashboard
├── scripts/
│   ├── backtest.py          # Walk-forward backtest CLI
│   ├── run_bot.py           # Bot entry point
│   └── start.sh             # Docker startup (bot + dashboard)
├── tests/
│   ├── test_connectivity.py # API smoke tests
│   ├── test_db.py
│   ├── test_scheduler.py
│   ├── test_sentiment.py
│   └── test_signal_gen.py
├── Dockerfile
├── docker-compose.yml
├── fly.toml                 # Fly.io deployment config
└── pyproject.toml           # pytest markers config
```

## Setup

### 1. Clone and create virtual environment

```bash
git clone <repo-url>
cd news-trading-bot
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Get API keys (all free tiers)

| Service  | URL                       | Notes                        |
|----------|---------------------------|------------------------------|
| Finnhub  | finnhub.io                | Free: 60 req/min             |
| FRED     | fred.stlouisfed.org       | Free: 120 req/min            |
| Alpaca   | alpaca.markets            | Free paper trading account   |
| OANDA    | oanda.com                 | Optional: forex/commodities  |
| Telegram | t.me/BotFather            | Optional: trade alerts       |

### 3. Configure `.env`

```env
FINNHUB_API_KEY=your_key
FRED_API_KEY=your_key
ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_key

# Optional
OANDA_API_KEY=your_key
OANDA_ACCOUNT_ID=001-001-1234567-001
OANDA_ENVIRONMENT=practice

TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

PAPER_TRADING=true
```

## Running

### Locally

```bash
# Start the trading bot
source venv/bin/activate
python scripts/run_bot.py

# Start the dashboard (separate terminal)
streamlit run dashboard/app.py

# Run a backtest on historical signals
python scripts/backtest.py
python scripts/backtest.py --hold-hours 2 --window-days 14 --min-confidence 0.5
```

### Docker (local)

```bash
docker compose up --build
```

Bot and dashboard share a SQLite volume at `./data/trading.db`.

### Fly.io

The app is deployed at `https://trading-bot-lingering-lake-4314.fly.dev`.

**Deploys are automatic** — every push to `main` triggers `.github/workflows/fly-deploy.yml`,
which builds and deploys to Fly.io via the `FLY_API_TOKEN` secret already configured in the repo.
Monitor runs under the **Actions** tab on GitHub.

For a first-time setup on a new Fly.io account:

```bash
fly auth login
fly launch        # generates fly.toml and fly-deploy.yml
fly secrets set FINNHUB_API_KEY=... FRED_API_KEY=... \
    ALPACA_API_KEY=... ALPACA_SECRET_KEY=... \
    TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=...
```

To deploy manually (bypassing GitHub Actions):

```bash
fly deploy
```

**Notes:**
- API keys are stored as Fly.io secrets — never put them in `fly.toml`
- The SQLite DB persists on a Fly.io volume (`trading_data` → `/app/data`)
- Machine runs with 2 GB RAM (required for PyTorch + FinBERT at runtime)
- Docker image uses CPU-only PyTorch to stay under Fly.io's 8 GB image limit

## Configuration Reference

All settings are in `config/settings.py` and overridable via environment variables.

| Variable                        | Default | Description                                  |
|---------------------------------|---------|----------------------------------------------|
| `NEWS_POLL_INTERVAL_SECONDS`    | 300     | How often to fetch news (seconds)            |
| `SIGNAL_CONVICTION_THRESHOLD`   | 0.4     | Minimum confidence to generate a signal      |
| `MAX_POSITION_PCT`              | 0.05    | Max portfolio % per position (5%)            |
| `MAX_HOLD_HOURS`                | 4.0     | Time-based exit after N hours                |
| `STOP_LOSS_PCT`                 | 0.02    | Trailing stop threshold (2%)                 |
| `MAX_DAILY_LOSS_PCT`            | 0.05    | Pause trading if down 5% intraday            |
| `MAX_TRADES_PER_DAY`            | 10      | Hard cap on daily executions                 |
| `POSITION_MONITOR_INTERVAL_SECONDS` | 120 | Exit check frequency                        |
| `DEDUP_SIMILARITY_THRESHOLD`    | 0.5     | Jaccard similarity threshold for dedup       |
| `DEDUP_WINDOW_HOURS`            | 4       | Look-back window for headline dedup          |
| `MACRO_REFRESH_CYCLES`          | 12      | Refresh FRED data every N poll cycles (~1hr) |
| `MAX_ARTICLES_PER_CYCLE`        | 50      | Max articles scored per poll (FinBERT ~2s/article) |
| `MAX_THEME_EXPOSURE_PCT`        | 0.15    | Max portfolio % exposed to one theme (15%)   |
| `MAX_TOTAL_EXPOSURE_PCT`        | 0.60    | Max total portfolio exposure (60%)           |
| `MIN_SOURCE_COUNT`              | 1       | Min distinct sources before executing (set 2 for production) |
| `CORROBORATION_WINDOW_HOURS`    | 4       | Look-back window for multi-source confirmation |
| `NEWS_FETCH_TIMEOUT_SECONDS`    | 10      | Per-feed HTTP timeout                        |
| `PAPER_TRADING`                 | true    | Set to `false` to enable live trading        |

## Trading Signals

The rules engine covers 17 themes mapped to 4 instruments:

| Theme                  | Instrument | Trigger Examples                                  |
|------------------------|------------|---------------------------------------------------|
| `fed_hawkish`          | SPY        | "rate hike", "hawkish", "tightening"              |
| `fed_dovish`           | SPY        | "rate cut", "dovish", "pivot"                     |
| `jobs_strong`          | SPY        | "nonfarm payroll", "hiring surge"                 |
| `inflation`            | SPY        | "CPI", "consumer prices", "inflationary"          |
| `recession_risk`       | SPY        | "recession", "GDP falls", "contraction"           |
| `geopolitical_risk`    | SPY        | "war", "sanctions", "invasion"                    |
| `market_rally`         | SPY        | "record high", "bull market"                      |
| `usd_strength`         | EUR_USD    | "dollar surges", "DXY rises"                      |
| `usd_weakness`         | EUR_USD    | "dollar falls", "weak dollar"                     |
| `gold_safe_haven`      | XAU_USD    | "gold rises", "safe haven demand"                 |
| `gold_selloff`         | XAU_USD    | "gold drops", "risk-on", "gold tumbles"           |
| `gold_inflation_hedge` | XAU_USD    | "real yields fall", "inflation hedge", "debasement"|
| `gold_geopolitical`    | XAU_USD    | "gold spikes", "investors flee to gold"           |
| `oil_supply_squeeze`   | BCO_USD    | "OPEC cuts", "production cut", "tight supply"     |
| `oil_demand_growth`    | BCO_USD    | "China oil demand", "fuel demand rises"           |
| `oil_oversupply`       | BCO_USD    | "oil glut", "OPEC hike", "oil surplus"            |
| `oil_geopolitical`     | BCO_USD    | "Strait of Hormuz", "pipeline attack", "sanctions"|

## Risk Management

- Max 5% of portfolio per position (configurable)
- 5% intraday loss → trading paused until restart
- 10 trades/day cap (configurable)
- 2% trailing stop on all positions
- 4-hour time-based exit if thesis hasn't played out
- 15% max exposure to any single theme (MAX_THEME_EXPOSURE_PCT)
- 60% max total portfolio exposure across all open positions (MAX_TOTAL_EXPOSURE_PCT)
- Short-sell guard: sell signals are skipped if no existing position held (equities only; forex allows native shorting)
- Multi-source confirmation: MIN_SOURCE_COUNT=1 for paper trading, set to 2 for production to require corroboration before executing
- OANDA signals skipped if OANDA keys are not configured

## Tests

```bash
# Run fast unit tests (no API keys or model download needed)
pytest tests/ -m 'not integration and not slow'

# Run all tests including integration (requires API keys in .env)
pytest tests/ -m integration

# Run sentiment tests (requires FinBERT model download, ~440 MB)
pytest tests/ -m slow
```

Test files:

| File | Marks | What It Tests |
|------|-------|---------------|
| `test_connectivity.py` | `@integration` | Finnhub, FRED, Alpaca API connectivity + schema validation |
| `test_sentiment.py` | `@slow` | FinBERT model loading, scoring accuracy, edge cases |
| `test_signal_gen.py` | — | Theme classification, action mapping, confidence thresholds |
| `test_db.py` | — | SQLite schema, article/signal CRUD, dedup by ID |
| `test_scheduler.py` | — | Scheduler wiring and pipeline integration |

## Backtesting

```bash
python scripts/backtest.py
```

Uses yfinance to fetch historical prices for each signal's entry and exit time. Reports win rate, average return, max drawdown, and profit factor — broken down by time window, theme, and ticker.

**Note:** yfinance 1-minute data only goes back 7 days. Backtest quality improves as the bot accumulates signal history over weeks of live paper trading.

## Dashboard

The Streamlit dashboard runs on port 8501. It has four tabs:

**Portfolio tab**
- Combined equity summary (Alpaca + OANDA), cash, buying power, and daily P&L
- Open positions table with unrealized P&L for both Alpaca (equities) and OANDA (forex)
- Open orders list
- Recent closed trades across both brokers
- Portfolio value ($) and return (%) charts with selectable periods (1D / 1W / 1M / 3M / 1Y)

**Signals tab**
- Signal history with executed / skipped / pending / expired status filters
- Per-signal detail: ticker, theme, confidence score, rationale, timestamps

**News tab**
- Recent ingested articles filterable by sentiment (positive / negative / neutral)
- Sentiment breakdown counts and per-article FinBERT scores

**Audit tab**
- Rolling signal quality metrics (configurable window: 6h / 12h / 24h / 48h)
- Anomaly detection alerts (high skip rate, high expiry rate, theme concentration, missing feeds, position accumulation)
- Per-theme signal breakdown with skip rate, expiry rate, and average confidence
- Pipeline health: article counts by source
- Trade P&L by theme (closed positions only)

**Sidebar**
- FRED macro indicators grouped by category (Policy, Growth/Labour, Rates/Spreads, Risk/FX)
- Paper trading mode indicator

## Alerts

Telegram alerts are sent by `core/alerts.py`. All alert functions no-op silently if `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID` are not configured.

| Alert | When | Content |
|-------|------|---------|
| Signal execution | On each executed trade | Ticker, action, qty, confidence, theme, order ID |
| Hourly P&L digest | Top of each hour, 09:00–16:00 ET | Signals summary, portfolio equity/cash, open positions with unrealized P&L |
| Position exit | On trailing stop or time-based exit | Ticker, exit reason, order ID |
| Daily audit report | 16:10 ET, Mon–Fri (after market close) | 24h signal stats, per-theme breakdown, pipeline health, anomalies |
| Startup | On bot start | Confirmation message |
| Shutdown | On clean shutdown (Ctrl-C or SIGTERM) | Confirmation message |
