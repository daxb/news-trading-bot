import os
import sys
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# API keys (loaded from .env)
FINNHUB_API_KEY = os.getenv('FINNHUB_API_KEY', '')
FRED_API_KEY = os.getenv('FRED_API_KEY', '')
ALPACA_API_KEY = os.getenv('ALPACA_API_KEY', '')
ALPACA_SECRET_KEY = os.getenv('ALPACA_SECRET_KEY', '')

# Trading mode — default to paper
PAPER_TRADING = os.getenv('PAPER_TRADING', 'true').lower() != 'false'

# Warn if going live
if not PAPER_TRADING:
    print(
        '\n' + '=' * 60,
        'WARNING: LIVE TRADING ENABLED',
        'PAPER_TRADING is set to False. Real money at risk.',
        '=' * 60 + '\n',
        file=sys.stderr
    )

# Alpaca endpoints
ALPACA_BASE_URL = (
    "https://paper-api.alpaca.markets" if PAPER_TRADING
    else "https://api.alpaca.markets"
)

# Database
DB_PATH = os.getenv(
    'DB_PATH',
    os.path.join(os.path.dirname(__file__), '..', 'data', 'trading.db')
)

# Pipeline config
NEWS_POLL_INTERVAL_SECONDS = int(os.getenv('NEWS_POLL_INTERVAL_SECONDS', 300))
SIGNAL_CONVICTION_THRESHOLD = float(os.getenv('SIGNAL_CONVICTION_THRESHOLD', 0.4))

# Risk limits
MAX_POSITION_PCT = float(os.getenv('MAX_POSITION_PCT', 0.05))
MAX_THEME_EXPOSURE_PCT = float(os.getenv('MAX_THEME_EXPOSURE_PCT', 0.15))
MAX_TOTAL_EXPOSURE_PCT = float(os.getenv('MAX_TOTAL_EXPOSURE_PCT', 0.60))
STOP_LOSS_PCT = float(os.getenv('STOP_LOSS_PCT', 0.02))
MAX_DAILY_LOSS_PCT = float(os.getenv('MAX_DAILY_LOSS_PCT', 0.05))
MAX_TRADES_PER_DAY = int(os.getenv('MAX_TRADES_PER_DAY', 10))

# OANDA forex (Phase 2)
OANDA_API_KEY = os.getenv('OANDA_API_KEY', '')
OANDA_ACCOUNT_ID = os.getenv('OANDA_ACCOUNT_ID', '')
OANDA_ENVIRONMENT = os.getenv('OANDA_ENVIRONMENT', 'practice')  # 'practice' or 'live'

# Telegram alerts
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')

# News deduplication
DEDUP_SIMILARITY_THRESHOLD = float(os.getenv('DEDUP_SIMILARITY_THRESHOLD', 0.5))
DEDUP_WINDOW_HOURS = int(os.getenv('DEDUP_WINDOW_HOURS', 4))

# Macro context — FRED indicator thresholds and refresh cadence
MACRO_REFRESH_CYCLES = int(os.getenv('MACRO_REFRESH_CYCLES', 12))  # every ~1 hr at 5 min polls
FEDFUNDS_HIGH = float(os.getenv('FEDFUNDS_HIGH', 4.0))   # rates considered elevated
FEDFUNDS_LOW = float(os.getenv('FEDFUNDS_LOW', 2.0))     # rates considered low
UNRATE_HIGH = float(os.getenv('UNRATE_HIGH', 5.5))       # unemployment considered elevated
UNRATE_LOW = float(os.getenv('UNRATE_LOW', 4.0))         # unemployment considered tight
DGS10_HIGH = float(os.getenv('DGS10_HIGH', 4.0))         # 10-yr yield considered elevated
