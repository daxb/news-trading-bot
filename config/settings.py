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

# Telegram alerts
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
