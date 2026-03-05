"""
Manual test: verify OANDA connectivity.
Usage: python dev/test_oanda.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.forex import ForexBroker

broker = ForexBroker()

print("\n--- Account ---")
acct = broker.get_account()
for k, v in acct.items():
    print(f"  {k}: {v}")

print("\n--- Prices ---")
for instrument in ("EUR_USD", "GBP_USD", "XAU_USD", "BCO_USD"):
    price = broker.get_latest_price(instrument)
    print(f"  {instrument}: {price}")

print("\n--- Open Positions ---")
positions = broker.get_positions()
if positions:
    for p in positions:
        print(f"  {p}")
else:
    print("  No open positions")

print("\nOANDA connectivity OK")
