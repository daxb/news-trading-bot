"""
Position exit manager for the Macro Trader bot.

Runs on a separate scheduler job (every POSITION_MONITOR_INTERVAL_SECONDS)
and closes positions when either of two conditions is met:

  1. Time-based exit  — position has been held >= MAX_HOLD_HOURS
  2. Trailing stop    — price has dropped >= STOP_LOSS_PCT from its peak
                        (or risen >= STOP_LOSS_PCT from trough for shorts)

Peak/trough prices are tracked in memory and reset when the bot restarts.
This is acceptable for MVP — positions are short-lived (2–4 hours) so
a restart mid-hold would simply re-evaluate from the current price.
"""

import logging
from datetime import datetime, timezone

from config import settings
from core.alerts import send_exit_alert
from core.broker import BrokerClient
from core.db import Database

logger = logging.getLogger(__name__)


class ExitManager:
    """Monitors open positions and closes them on exit conditions."""

    def __init__(
        self,
        broker: BrokerClient,
        db: Database,
        forex=None,   # ForexBroker | None — typed loosely to avoid circular import
    ) -> None:
        self._broker = broker
        self._forex = forex
        self._db = db
        self._peak_prices: dict[str, float] = {}  # high-water marks (long) / low-water marks (short)
        logger.info(
            "ExitManager ready — max_hold=%.1fh, trailing_stop=%.1f%%",
            settings.MAX_HOLD_HOURS,
            settings.STOP_LOSS_PCT * 100,
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def check_exits(self) -> None:
        """Check all open positions. Called by the scheduler every N seconds."""
        self._check_equity_positions()
        if self._forex:
            self._check_forex_positions()

    # ------------------------------------------------------------------
    # Per-broker loops
    # ------------------------------------------------------------------

    def _check_equity_positions(self) -> None:
        positions = self._broker.get_positions()
        for pos in positions:
            ticker = pos["symbol"]
            current_price = self._broker.get_latest_price(ticker)
            if current_price is None:
                logger.warning("Could not get price for %s — skipping exit check", ticker)
                continue
            self._evaluate(ticker, pos["side"], current_price, is_forex=False)

    def _check_forex_positions(self) -> None:
        positions = self._forex.get_positions()
        for pos in positions:
            instrument = pos["instrument"]
            current_price = self._forex.get_latest_price(instrument)
            if current_price is None:
                logger.warning("Could not get price for %s — skipping exit check", instrument)
                continue
            side = pos["side"]  # "long" or "short"
            self._evaluate(instrument, side, current_price, is_forex=True)

    # ------------------------------------------------------------------
    # Exit logic
    # ------------------------------------------------------------------

    def _evaluate(
        self, ticker: str, side: str, current_price: float, is_forex: bool
    ) -> None:
        """Check and act on exit conditions for a single position."""
        self._update_peak(ticker, side, current_price)

        # 1. Time-based exit
        reason = self._time_exit_reason(ticker)
        if reason:
            self._close(ticker, reason, is_forex)
            return

        # 2. Trailing stop
        reason = self._trailing_stop_reason(ticker, side, current_price)
        if reason:
            self._close(ticker, reason, is_forex)

    def _update_peak(self, ticker: str, side: str, price: float) -> None:
        if ticker not in self._peak_prices:
            self._peak_prices[ticker] = price
            return
        if side == "long":
            self._peak_prices[ticker] = max(self._peak_prices[ticker], price)
        else:
            self._peak_prices[ticker] = min(self._peak_prices[ticker], price)

    def _time_exit_reason(self, ticker: str) -> str | None:
        """Return a reason string if the position has exceeded MAX_HOLD_HOURS."""
        signal = self._db.get_last_executed_signal(ticker)
        if not signal or not signal.get("executed_at"):
            return None

        try:
            executed_at = datetime.fromisoformat(signal["executed_at"])
            if executed_at.tzinfo is None:
                executed_at = executed_at.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

        hold_hours = (datetime.now(timezone.utc) - executed_at).total_seconds() / 3600
        if hold_hours >= settings.MAX_HOLD_HOURS:
            return f"time-based exit ({hold_hours:.1f}h ≥ {settings.MAX_HOLD_HOURS}h limit)"
        return None

    def _trailing_stop_reason(
        self, ticker: str, side: str, current_price: float
    ) -> str | None:
        """Return a reason string if the trailing stop has been triggered."""
        peak = self._peak_prices.get(ticker)
        if peak is None or peak == 0:
            return None

        if side == "long":
            drawdown = (peak - current_price) / peak
            if drawdown >= settings.STOP_LOSS_PCT:
                return (
                    f"trailing stop ({drawdown:.1%} drawdown "
                    f"from peak {peak:.5g})"
                )
        else:  # short
            rise = (current_price - peak) / peak
            if rise >= settings.STOP_LOSS_PCT:
                return (
                    f"trailing stop ({rise:.1%} rise "
                    f"from trough {peak:.5g})"
                )
        return None

    # ------------------------------------------------------------------
    # Order execution
    # ------------------------------------------------------------------

    def _close(self, ticker: str, reason: str, is_forex: bool) -> None:
        logger.info("Closing %s: %s", ticker, reason)
        broker = self._forex if is_forex else self._broker
        order = broker.close_position(ticker)
        if order:
            # Record exit price against the originating signal for P&L tracking
            exit_price = broker.get_latest_price(ticker)
            if exit_price:
                signal = self._db.get_last_executed_signal(ticker)
                if signal:
                    self._db.update_signal_exit_price(signal["id"], exit_price)
            # Clear peak tracking for this position
            self._peak_prices.pop(ticker, None)
            send_exit_alert(ticker, reason, order.get("id", ""))
        else:
            logger.warning("Failed to close %s — will retry next cycle", ticker)
