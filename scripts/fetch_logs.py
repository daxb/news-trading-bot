"""
Fetch logs from the Fly.io deployment and save them locally for review.

Usage:
    python scripts/fetch_logs.py              # last 200 lines
    python scripts/fetch_logs.py -n 500       # last 500 lines
    python scripts/fetch_logs.py --errors     # ERROR lines only
    python scripts/fetch_logs.py --signals    # [SIGNAL] lines only
    python scripts/fetch_logs.py --orders     # [ORDER] lines only
    python scripts/fetch_logs.py --risk       # [RISK] lines only

Saved to: logs/fly_YYYY-MM-DD_HH-MM.txt
"""

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

APP_NAME = "trading-bot-lingering-lake-4314"
LOGS_DIR = Path(__file__).parent.parent / "logs"


def _check_flyctl() -> None:
    if not shutil.which("flyctl"):
        print(
            "ERROR: flyctl not found. Install it from https://fly.io/docs/hands-on/install-flyctl/",
            file=sys.stderr,
        )
        sys.exit(1)


def fetch(lines: int) -> list[str]:
    """Run flyctl logs and return raw lines."""
    cmd = ["flyctl", "logs", "--app", APP_NAME, "-n", str(lines)]
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: flyctl exited {result.returncode}", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    return result.stdout.splitlines()


def save(log_lines: list[str]) -> Path:
    """Write lines to a timestamped file under logs/."""
    LOGS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    out_path = LOGS_DIR / f"fly_{ts}.txt"
    out_path.write_text("\n".join(log_lines) + "\n")
    return out_path


def summarise(log_lines: list[str]) -> None:
    """Print a quick breakdown of key event counts."""
    total   = len(log_lines)
    signals = sum(1 for l in log_lines if "[SIGNAL]" in l)
    orders  = sum(1 for l in log_lines if "[ORDER]"  in l)
    risk    = sum(1 for l in log_lines if "[RISK]"   in l)
    errors  = sum(1 for l in log_lines if " ERROR " in l or "[ERROR]" in l)
    warnings = sum(1 for l in log_lines if " WARNING " in l)

    print("\n--- Log Summary ---")
    print(f"  Total lines : {total}")
    print(f"  [SIGNAL]    : {signals}")
    print(f"  [ORDER]     : {orders}")
    print(f"  [RISK]      : {risk}")
    print(f"  ERROR       : {errors}")
    print(f"  WARNING     : {warnings}")
    print("-------------------\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Fly.io logs for FIONA")
    parser.add_argument("-n", type=int, default=200, help="Number of log lines to fetch (default: 200)")
    parser.add_argument("--errors",  action="store_true", help="Print ERROR lines to stdout")
    parser.add_argument("--signals", action="store_true", help="Print [SIGNAL] lines to stdout")
    parser.add_argument("--orders",  action="store_true", help="Print [ORDER] lines to stdout")
    parser.add_argument("--risk",    action="store_true", help="Print [RISK] lines to stdout")
    args = parser.parse_args()

    _check_flyctl()
    log_lines = fetch(args.n)
    out_path = save(log_lines)
    summarise(log_lines)
    print(f"Saved to: {out_path}")

    # Optional filtered output to stdout
    filters = {
        "errors":  (args.errors,  lambda l: " ERROR " in l or "[ERROR]" in l),
        "signals": (args.signals, lambda l: "[SIGNAL]" in l),
        "orders":  (args.orders,  lambda l: "[ORDER]"  in l),
        "risk":    (args.risk,    lambda l: "[RISK]"   in l),
    }
    for label, (active, predicate) in filters.items():
        if active:
            matched = [l for l in log_lines if predicate(l)]
            print(f"\n--- {label.upper()} ({len(matched)}) ---")
            for line in matched:
                print(line)


if __name__ == "__main__":
    main()
