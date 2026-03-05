"""
Walk-forward backtesting engine for the Macro Trader bot.

For each signal in the DB, fetches the entry price at signal creation time
and exit price after a configurable hold period using yfinance. Aggregates
results into rolling time windows to surface consistency (or drift) over time.

Limitations
-----------
- Only signals that already have an exit price available are simulated
  (signals generated in the last `hold_hours` are skipped)
- Position sizing is fixed at `position_size` dollars per trade
- Slippage and commissions are not modelled
- yfinance 1m data only goes back 7 days; 1h goes back ~730 days
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pandas as pd
import yfinance as yf

from config import settings
from core.db import Database

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ticker mapping: bot instrument → yfinance symbol
# ---------------------------------------------------------------------------
_YF_MAP: dict[str, str] = {
    "SPY":     "SPY",
    "EUR_USD": "EURUSD=X",
    "GBP_USD": "GBPUSD=X",
    "XAU_USD": "GC=F",   # Gold futures
    "BCO_USD": "BZ=F",   # Brent crude futures
}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class TradeResult:
    signal_id:   int
    ticker:      str
    action:      str
    theme:       str
    confidence:  float
    entry_time:  datetime
    exit_time:   datetime
    entry_price: float
    exit_price:  float

    @property
    def pnl_pct(self) -> float:
        """Return % P&L from the trade (positive = profitable)."""
        if self.entry_price == 0:
            return 0.0
        if self.action == "buy":
            return (self.exit_price - self.entry_price) / self.entry_price
        else:
            return (self.entry_price - self.exit_price) / self.entry_price

    @property
    def correct(self) -> bool:
        return self.pnl_pct > 0


@dataclass
class WindowResult:
    start:  datetime
    end:    datetime
    trades: list[TradeResult] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        return sum(1 for t in self.trades if t.correct) / len(self.trades) if self.trades else 0.0

    @property
    def avg_return_pct(self) -> float:
        return sum(t.pnl_pct for t in self.trades) / len(self.trades) if self.trades else 0.0

    @property
    def total_return_pct(self) -> float:
        result = 1.0
        for t in self.trades:
            result *= (1 + t.pnl_pct)
        return result - 1.0

    @property
    def max_drawdown_pct(self) -> float:
        if not self.trades:
            return 0.0
        equity, peak, max_dd = 1.0, 1.0, 0.0
        for t in self.trades:
            equity *= (1 + t.pnl_pct)
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak)
        return max_dd

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.pnl_pct for t in self.trades if t.pnl_pct > 0)
        gross_loss   = abs(sum(t.pnl_pct for t in self.trades if t.pnl_pct < 0))
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0
        return gross_profit / gross_loss


# ---------------------------------------------------------------------------
# Backtester
# ---------------------------------------------------------------------------

class Backtester:
    """
    Simulates historical signal execution using yfinance price data.

    Args:
        db:            Database instance to load signals from.
        hold_hours:    Hours to hold each position before exiting.
        position_size: Fixed dollar amount per trade for P&L calculation.
    """

    def __init__(
        self,
        db: Database,
        hold_hours: int = 4,
        position_size: float = 5000.0,
    ) -> None:
        self._db = db
        self._hold_hours = hold_hours
        self._position_size = position_size
        self._price_cache: dict[str, pd.Series] = {}
        self._failed_fetches: set[str] = set()  # avoid retrying known-bad downloads

    # ------------------------------------------------------------------
    # Price fetching
    # ------------------------------------------------------------------

    def _fetch_prices(self, ticker: str, start: datetime, end: datetime) -> pd.Series | None:
        """Download and cache a close-price series for a ticker."""
        cache_key = f"{ticker}|{start.date()}|{end.date()}"
        if cache_key in self._price_cache:
            return self._price_cache[cache_key]
        if cache_key in self._failed_fetches:
            return None

        yf_ticker = _YF_MAP.get(ticker)
        if not yf_ticker:
            logger.warning("No yfinance mapping for '%s' — skipping", ticker)
            return None

        age_days = (datetime.now(timezone.utc) - start).days
        if age_days <= 7:
            interval = "1m"
        elif age_days <= 730:
            interval = "1h"
        else:
            interval = "1d"

        try:
            raw = yf.download(
                yf_ticker,
                start=start - timedelta(hours=2),
                end=end + timedelta(hours=self._hold_hours + 2),
                interval=interval,
                progress=False,
                auto_adjust=True,
            )
            if raw.empty:
                logger.warning("yfinance returned no data for %s (%s)", ticker, yf_ticker)
                self._failed_fetches.add(cache_key)
                return None

            # Handle MultiIndex columns (newer yfinance versions)
            close = raw["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]

            # Normalise index to UTC
            if close.index.tz is None:
                close.index = close.index.tz_localize("UTC")
            else:
                close.index = close.index.tz_convert("UTC")

            self._price_cache[cache_key] = close
            return close

        except Exception:
            logger.exception("Failed to fetch price data for %s", ticker)
            self._failed_fetches.add(cache_key)
            return None

    def _price_at(self, prices: pd.Series, dt: datetime) -> float | None:
        """Return the last available price at or before dt."""
        try:
            idx = prices.index.asof(dt)
            if pd.isna(idx):
                return None
            val = prices[idx]
            return float(val) if not pd.isna(val) else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Trade simulation
    # ------------------------------------------------------------------

    def _simulate(self, signal: dict) -> TradeResult | None:
        """Simulate a single trade. Returns None if data is unavailable."""
        raw_ts = signal.get("created_at", "")
        if not raw_ts:
            return None

        try:
            entry_time = datetime.fromisoformat(raw_ts)
            if entry_time.tzinfo is None:
                entry_time = entry_time.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

        exit_time = entry_time + timedelta(hours=self._hold_hours)

        # Skip signals where the exit hasn't happened yet
        if exit_time > datetime.now(timezone.utc):
            return None

        ticker = signal.get("ticker", "")
        prices = self._fetch_prices(ticker, entry_time, exit_time)
        if prices is None:
            return None

        entry_price = self._price_at(prices, entry_time)
        exit_price  = self._price_at(prices, exit_time)

        if entry_price is None or exit_price is None:
            return None

        return TradeResult(
            signal_id=signal["id"],
            ticker=ticker,
            action=signal.get("action", ""),
            theme=signal.get("theme", ""),
            confidence=signal.get("confidence", 0.0),
            entry_time=entry_time,
            exit_time=exit_time,
            entry_price=entry_price,
            exit_price=exit_price,
        )

    # ------------------------------------------------------------------
    # Walk-forward runner
    # ------------------------------------------------------------------

    def run(
        self,
        window_days: int = 7,
        min_confidence: float = 0.0,
    ) -> list[WindowResult]:
        """
        Run the walk-forward backtest.

        Args:
            window_days:    Size of each rolling window in days.
            min_confidence: Only include signals above this confidence.

        Returns:
            List of WindowResult objects, one per window.
        """
        all_signals = self._db.get_signals(limit=10_000)

        if min_confidence > 0:
            all_signals = [s for s in all_signals if s.get("confidence", 0) >= min_confidence]

        if not all_signals:
            logger.warning("No signals found in DB to backtest")
            return []

        # Sort oldest first
        all_signals.sort(key=lambda s: s.get("created_at", ""))

        def _parse(ts: str) -> datetime:
            dt = datetime.fromisoformat(ts)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

        first_dt = _parse(all_signals[0]["created_at"])
        last_dt  = _parse(all_signals[-1]["created_at"])

        # Build non-overlapping windows from first signal date
        windows: list[WindowResult] = []
        window_start = first_dt.replace(hour=0, minute=0, second=0, microsecond=0)

        while window_start <= last_dt:
            window_end = window_start + timedelta(days=window_days)
            window = WindowResult(start=window_start, end=window_end)

            for sig in all_signals:
                sig_dt = _parse(sig["created_at"])
                if window_start <= sig_dt < window_end:
                    result = self._simulate(sig)
                    if result:
                        window.trades.append(result)

            windows.append(window)
            window_start = window_end

        return windows
