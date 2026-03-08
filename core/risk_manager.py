"""
Risk management for the Macro Trader bot.

Enforces four guards before any order is submitted:
  1. MAX_TRADES_PER_DAY       — hard cap on daily executions
  2. MAX_DAILY_LOSS_PCT       — pause if portfolio drops too much intraday
  3. Position sizing          — size each order at MAX_POSITION_PCT of equity
  4. Per-ticker accumulation  — block additional BUY if already holding a long position

The start-of-session equity baseline is persisted in the DB so a mid-day
restart does not reset the daily loss guard to the post-crash equity level.
"""

import logging
from datetime import datetime, timezone

from config import settings
from core.broker import BrokerClient
from core.db import Database

logger = logging.getLogger(__name__)


class RiskManager:
    """Stateful risk guard — one instance shared across the session."""

    def __init__(self, broker: BrokerClient, db: Database) -> None:
        self._broker = broker
        self._db = db
        self._start_equity = self._load_or_init_session_equity()
        logger.info(
            "RiskManager ready — start_equity=%.2f, max_trades/day=%d, "
            "max_daily_loss=%.1f%%, max_position=%.1f%%",
            self._start_equity,
            settings.MAX_TRADES_PER_DAY,
            settings.MAX_DAILY_LOSS_PCT * 100,
            settings.MAX_POSITION_PCT * 100,
        )

    def _load_or_init_session_equity(self) -> float:
        """
        Return the session baseline equity for today's daily loss calculation.

        If the DB already holds a baseline for today (UTC), reuse it so that
        a mid-day bot restart does not reset the loss guard. Otherwise fetch
        current equity from the broker, persist it, and use it as the baseline.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        stored_date = self._db.get_state("session_equity_date")
        if stored_date == today:
            stored_val = self._db.get_state("session_equity_value")
            if stored_val:
                try:
                    equity = float(stored_val)
                    logger.info(
                        "RiskManager: restored session baseline equity=%.2f from DB", equity
                    )
                    return equity
                except ValueError:
                    pass  # corrupted value — fall through to re-fetch

        account = self._broker.get_account()
        equity = account.get("equity", 0.0)
        self._db.set_state("session_equity_date", today)
        self._db.set_state("session_equity_value", str(equity))
        logger.info("RiskManager: new session baseline equity=%.2f", equity)
        return equity

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    def can_trade(
        self,
        ticker: str | None = None,
        action: str | None = None,
    ) -> tuple[bool, str]:
        """
        Return (True, '') if it is safe to submit an order.
        Return (False, reason) if a risk limit is breached.

        Args:
            ticker: Instrument to trade (optional — enables per-ticker guard).
            action: 'buy' or 'sell' (optional — required for per-ticker guard).
        """
        # 1. Daily trade count
        trades_today = self._db.count_executed_today()
        if trades_today >= settings.MAX_TRADES_PER_DAY:
            reason = (
                f"Daily trade limit reached "
                f"({trades_today}/{settings.MAX_TRADES_PER_DAY})"
            )
            logger.warning(reason)
            return False, reason

        # 2. Daily loss
        account = self._broker.get_account()
        current_equity = account.get("equity", self._start_equity)
        if self._start_equity > 0:
            loss_pct = (self._start_equity - current_equity) / self._start_equity
            if loss_pct >= settings.MAX_DAILY_LOSS_PCT:
                reason = (
                    f"Daily loss limit breached "
                    f"({loss_pct:.1%} >= {settings.MAX_DAILY_LOSS_PCT:.1%})"
                )
                logger.warning(reason)
                return False, reason

        # 3. Per-ticker accumulation guard — block additional BUYs if already long
        if ticker and action and action.lower() == "buy":
            position = self._broker.get_position(ticker)
            if position:
                reason = (
                    f"Already hold a position in {ticker} "
                    f"— skipping additional BUY to prevent accumulation"
                )
                logger.warning(reason)
                return False, reason

        return True, ""

    # ------------------------------------------------------------------
    # Position sizing
    # ------------------------------------------------------------------

    def position_qty(self, ticker: str) -> float:
        """
        Return the number of shares to trade for a new position.

        Sizes at MAX_POSITION_PCT of current equity. Returns 0.0 if the
        price lookup fails or the resulting qty is below the 0.01 minimum.
        """
        account = self._broker.get_account()
        equity = account.get("equity", 0.0)
        if equity <= 0:
            logger.warning("position_qty: equity is %.2f — skipping", equity)
            return 0.0

        dollar_amount = equity * settings.MAX_POSITION_PCT

        price = self._broker.get_latest_price(ticker)
        if not price:
            logger.warning("position_qty: no price for %s — skipping", ticker)
            return 0.0

        qty = round(dollar_amount / price, 2)
        if qty < 0.01:
            logger.warning(
                "position_qty: computed qty %.4f below minimum (0.01) for %s",
                qty, ticker,
            )
            return 0.0

        logger.info(
            "Position size %s: $%.2f equity × %.1f%% = $%.2f → %.2f shares @ $%.2f",
            ticker, equity, settings.MAX_POSITION_PCT * 100, dollar_amount, qty, price,
        )
        return qty
