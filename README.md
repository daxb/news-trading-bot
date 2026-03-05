# Macro Trader Bot

A news-driven algorithmic trading bot that ingests macro-economic and geopolitical news, scores it with FinBERT sentiment analysis, and executes paper trades across equities (Alpaca), forex (OANDA), and commodities.

## How It Works

```
News (Finnhub + RSS) → FinBERT Sentiment → Rules Engine → Macro Filter → Risk Manager → Broker
```

Every 5 minutes the bot:
1. Fetches headlines from Finnhub and 5 RSS feeds (BBC, CNBC, MarketWatch, Yahoo Finance) concurrently
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
│   └── test_connectivity.py # API smoke tests
├── Dockerfile
├── docker-compose.yml
└── fly.toml                 # Fly.io deployment config
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

```bash
fly auth login
fly launch   # first time only
fly deploy
```

Set secrets on Fly.io (do not put keys in fly.toml):

```bash
fly secrets set FINNHUB_API_KEY=... FRED_API_KEY=... \
    ALPACA_API_KEY=... ALPACA_SECRET_KEY=... \
    TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=...
```

The dashboard is exposed at `https://<app-name>.fly.dev`.

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
| `PAPER_TRADING`                 | true    | Set to `false` to enable live trading        |

## Trading Signals

The rules engine covers 11 themes mapped to 4 instruments:

| Theme               | Instrument | Trigger Examples                          |
|---------------------|------------|-------------------------------------------|
| `fed_hawkish`       | SPY        | "rate hike", "hawkish", "tightening"      |
| `fed_dovish`        | SPY        | "rate cut", "dovish", "pivot"             |
| `jobs_strong`       | SPY        | "nonfarm payroll", "hiring surge"         |
| `inflation`         | SPY        | "CPI", "consumer prices", "inflationary"  |
| `recession_risk`    | SPY        | "recession", "GDP falls", "contraction"   |
| `geopolitical_risk` | SPY        | "war", "sanctions", "invasion"            |
| `market_rally`      | SPY        | "record high", "bull market"              |
| `usd_strength`      | EUR_USD    | "dollar surges", "DXY rises"              |
| `usd_weakness`      | EUR_USD    | "dollar falls", "weak dollar"             |
| `gold_safe_haven`   | XAU_USD    | "gold rises", "safe haven demand"         |
| `oil_demand`        | BCO_USD    | "OPEC cuts", "crude rally"                |

## Risk Management

- Max 5% of portfolio per position (configurable)
- 5% intraday loss → trading paused until restart
- 10 trades/day cap (configurable)
- 2% trailing stop on all positions
- 4-hour time-based exit if thesis hasn't played out
- OANDA signals skipped if OANDA keys are not configured

## Backtesting

```bash
python scripts/backtest.py
```

Uses yfinance to fetch historical prices for each signal's entry and exit time. Reports win rate, average return, max drawdown, and profit factor — broken down by time window, theme, and ticker.

**Note:** yfinance 1-minute data only goes back 7 days. Backtest quality improves as the bot accumulates signal history over weeks of live paper trading.

## Dashboard

The Streamlit dashboard at port 8501 shows:
- Portfolio value, cash, buying power (live from Alpaca)
- Open positions with P&L
- Signal history with status filters (executed / skipped / pending)
- News feed with sentiment breakdown
- Live FRED macro indicators in the sidebar
