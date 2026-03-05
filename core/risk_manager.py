"""
Risk management for the Macro Trader bot.

Enforces three guards before any order is submitted:
  1. MAX_TRADES_PER_DAY  — hard cap on daily executions
  2. MAX_DAILY_LOSS_PCT  — pause if portfolio drops too much intraday
  3. Position sizing     — size each order at MAX_POSITION_PCT of equity

The start-of-session equity is recorded at construction and used as the
daily baseline. It resets when the bot restarts (acceptable for MVP).
"""

import logging

from config import settings
from core.broker import BrokerClient
from core.db import Database

logger = logging.getLogger(__name__)


class RiskManager:
    """Stateful risk guard — one instance shared across the session."""

    def __init__(self, broker: BrokerClient, db: Database) -> None:
        self._broker = broker
        self._db = db
        account = broker.get_account()
        self._start_equity = account.get("equity", 0.0)
        logger.info(
            "RiskManager ready — start_equity=%.2f, max_trades/day=%d, "
            "max_daily_loss=%.1f%%, max_position=%.1f%%",
            self._start_equity,
            settings.MAX_TRADES_PER_DAY,
            settings.MAX_DAILY_LOSS_PCT * 100,
            settings.MAX_POSITION_PCT * 100,
        )

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    def can_trade(self) -> tuple[bool, str]:
        """
        Return (True, '') if it is safe to submit an order.
        Return (False, reason) if a risk limit is breached.
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
