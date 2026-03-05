"""
Alpaca broker wrapper for the Macro Trader bot.

Uses alpaca-py (modern SDK) and returns plain dicts so the rest of
the codebase is fully decoupled from the SDK.
"""

import logging
import os
from typing import Optional

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestTradeRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus

from config import settings

logger = logging.getLogger(__name__)


class BrokerClient:
    """Thin wrapper around Alpaca's TradingClient."""

    def __init__(self) -> None:
        # Safety gate: block live trading unless explicitly allowed
        if not settings.PAPER_TRADING:
            allow_live = os.getenv("ALLOW_LIVE_TRADING", "").lower()
            if allow_live != "true":
                raise RuntimeError(
                    "Live trading is disabled. Set PAPER_TRADING=true in .env, "
                    "or set ALLOW_LIVE_TRADING=true to proceed at your own risk."
                )

        if not settings.ALPACA_API_KEY or not settings.ALPACA_SECRET_KEY:
            raise ValueError("ALPACA_API_KEY and ALPACA_SECRET_KEY must be set in .env")

        self._client = TradingClient(
            api_key=settings.ALPACA_API_KEY,
            secret_key=settings.ALPACA_SECRET_KEY,
            paper=settings.PAPER_TRADING,
        )
        self._data_client = StockHistoricalDataClient(
            api_key=settings.ALPACA_API_KEY,
            secret_key=settings.ALPACA_SECRET_KEY,
        )
        mode = "paper" if settings.PAPER_TRADING else "LIVE"
        logger.info("BrokerClient initialized in %s mode", mode)

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def get_account(self) -> dict:
        """Return account summary as a plain dict."""
        try:
            acct = self._client.get_account()
            return {
                "id": str(acct.id),
                "status": str(acct.status),
                "cash": float(acct.cash),
                "buying_power": float(acct.buying_power),
                "portfolio_value": float(acct.portfolio_value),
                "equity": float(acct.equity),
                "currency": str(acct.currency),
                "pattern_day_trader": bool(acct.pattern_day_trader),
            }
        except Exception:
            logger.exception("Failed to fetch account info")
            return {}

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    def get_positions(self) -> list[dict]:
        """Return all open positions as a list of plain dicts."""
        try:
            positions = self._client.get_all_positions()
            return [
                {
                    "symbol": str(p.symbol),
                    "qty": float(p.qty),
                    "side": str(p.side),
                    "market_value": float(p.market_value),
                    "avg_entry_price": float(p.avg_entry_price),
                    "current_price": float(p.current_price),
                    "unrealized_pl": float(p.unrealized_pl),
                    "unrealized_plpc": float(p.unrealized_plpc),
                }
                for p in positions
            ]
        except Exception:
            logger.exception("Failed to fetch positions")
            return []

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def submit_market_order(self, ticker: str, qty: float, side: str) -> dict:
        """Submit a market order. `side` must be 'buy' or 'sell'."""
        order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL

        request = MarketOrderRequest(
            symbol=ticker.upper(),
            qty=qty,
            side=order_side,
            time_in_force=TimeInForce.DAY,
        )

        try:
            order = self._client.submit_order(request)
            result = {
                "id": str(order.id),
                "symbol": str(order.symbol),
                "qty": str(order.qty),
                "side": str(order.side),
                "type": str(order.type),
                "status": str(order.status),
                "submitted_at": str(order.submitted_at),
            }
            logger.info(
                "Order submitted: %s %s %s -> %s",
                side.upper(), qty, ticker.upper(), result["status"],
            )
            return result
        except Exception:
            logger.exception("Failed to submit order: %s %s %s", side, qty, ticker)
            return {}

    def get_position(self, ticker: str) -> dict | None:
        """Return the open position for a ticker, or None if not held."""
        try:
            pos = self._client.get_open_position(ticker.upper())
            return {
                "symbol": str(pos.symbol),
                "qty": float(pos.qty),
                "side": str(pos.side),
                "market_value": float(pos.market_value),
            }
        except Exception:
            # 404 means no position — not a real error
            return None

    def get_latest_price(self, ticker: str) -> float | None:
        """Return the latest trade price for a ticker, or None on failure."""
        try:
            request = StockLatestTradeRequest(symbol_or_symbols=ticker.upper())
            trades = self._data_client.get_stock_latest_trade(request)
            price = float(trades[ticker.upper()].price)
            logger.debug("Latest price %s: %.4f", ticker.upper(), price)
            return price
        except Exception:
            logger.exception("Failed to get latest price for %s", ticker.upper())
            return None

    def get_orders(self, status: str = "all") -> list[dict]:
        """Fetch orders filtered by status ('open', 'closed', 'all')."""
        status_map = {
            "open": QueryOrderStatus.OPEN,
            "closed": QueryOrderStatus.CLOSED,
            "all": QueryOrderStatus.ALL,
        }
        query_status = status_map.get(status.lower(), QueryOrderStatus.ALL)

        try:
            request = GetOrdersRequest(status=query_status)
            orders = self._client.get_orders(request)
            return [
                {
                    "id": str(o.id),
                    "symbol": str(o.symbol),
                    "qty": str(o.qty),
                    "side": str(o.side),
                    "type": str(o.type),
                    "status": str(o.status),
                    "submitted_at": str(o.submitted_at),
                    "filled_at": str(o.filled_at) if o.filled_at else None,
                    "filled_avg_price": str(o.filled_avg_price) if o.filled_avg_price else None,
                }
                for o in orders
            ]
        except Exception:
            logger.exception("Failed to fetch orders (status=%s)", status)
            return []
