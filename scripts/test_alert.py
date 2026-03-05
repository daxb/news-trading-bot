import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from core.alerts import send_signal_alert

print(f"Token set: {bool(settings.TELEGRAM_BOT_TOKEN)}")
print(f"Chat ID set: {bool(settings.TELEGRAM_CHAT_ID)}")
print(f"Token preview: {settings.TELEGRAM_BOT_TOKEN[:10]}..." if settings.TELEGRAM_BOT_TOKEN else "Token: MISSING")

send_signal_alert({
    "action": "buy",
    "ticker": "SPY",
    "confidence": 0.82,
    "theme": "fed_dovish",
    "rationale": "Test alert from Macro Trader bot",
})
