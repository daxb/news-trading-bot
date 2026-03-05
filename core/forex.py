"""
OANDA forex broker wrapper for the Macro Trader bot.

Provides the same interface as core/broker.py (get_account, get_latest_price,
get_position, submit_market_order) so RiskManager works with it unchanged
via duck typing.

Instruments use OANDA format: EUR_USD, GBP_USD, XAU_USD, BCO_USD.
Units are whole integers — positive = long, negative = short.

Environment:
    OANDA_API_KEY       — personal access token from OANDA dashboard
    OANDA_ACCOUNT_ID    — account ID (e.g. 001-001-1234567-001)
    OANDA_ENVIRONMENT   — 'practice' (default) or 'live'
"""

import logging

from oandapyV20 import API
from oandapyV20.endpoints.accounts import AccountSummary
from oandapyV20.endpoints.orders import OrderCreate
from oandapyV20.endpoints.positions import OpenPositions, PositionClose, PositionDetails
from oandapyV20.endpoints.pricing import PricingInfo
from oandapyV20.exceptions import V20Error

from config import settings

logger = logging.getLogger(__name__)


class ForexBroker:
    """Thin OANDA wrapper — same public interface as BrokerClient."""

    def __init__(self) -> None:
        if not settings.OANDA_API_KEY:
            raise ValueError("OANDA_API_KEY must be set in .env")
        if not settings.OANDA_ACCOUNT_ID:
            raise ValueError("OANDA_ACCOUNT_ID must be set in .env")

        self._account_id = settings.OANDA_ACCOUNT_ID
        self._client = API(
            access_token=settings.OANDA_API_KEY,
            environment=settings.OANDA_ENVIRONMENT,
        )
        logger.info(
            "ForexBroker initialized (%s account)", settings.OANDA_ENVIRONMENT
        )

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def get_account(self) -> dict:
        """Return account summary. Keys match BrokerClient.get_account()."""
        try:
            r = AccountSummary(self._account_id)
            self._client.request(r)
            acct = r.response["account"]
            return {
                "equity":        float(acct["NAV"]),
                "cash":          float(acct["balance"]),
                "buying_power":  float(acct["marginAvailable"]),
                "portfolio_value": float(acct["NAV"]),
                "currency":      acct.get("currency", "USD"),
            }
        except Exception:
            logger.exception("Failed to fetch OANDA account")
            return {}

    # ------------------------------------------------------------------
    # Pricing
    # ------------------------------------------------------------------

    def get_latest_price(self, instrument: str) -> float | None:
        """Return the mid price for an OANDA instrument, or None on failure."""
        try:
            r = PricingInfo(
                self._account_id,
                params={"instruments": instrument.upper()},
            )
            self._client.request(r)
            price_data = r.response["prices"][0]
            bid = float(price_data["bids"][0]["price"])
            ask = float(price_data["asks"][0]["price"])
            mid = round((bid + ask) / 2, 5)
            logger.debug("Latest price %s: %.5f", instrument, mid)
            return mid
        except Exception:
            logger.exception("Failed to get latest price for %s", instrument)
            return None

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    def get_position(self, instrument: str) -> dict | None:
        """
        Return the open position for an instrument, or None if flat.

        Checks both long and short sides — returns whichever is non-zero.
        """
        try:
            r = PositionDetails(self._account_id, instrument.upper())
            self._client.request(r)
            pos = r.response["position"]
            long_units  = int(pos["long"]["units"])
            short_units = int(pos["short"]["units"])

            if long_units > 0:
                return {"instrument": instrument, "units": long_units, "side": "long"}
            if short_units < 0:
                return {"instrument": instrument, "units": short_units, "side": "short"}
            return None  # flat
        except V20Error as e:
            if "No position" in str(e) or "404" in str(e):
                return None
            logger.exception("Failed to get position for %s", instrument)
            return None
        except Exception:
            logger.exception("Failed to get position for %s", instrument)
            return None

    def get_positions(self) -> list[dict]:
        """Return all open forex positions as a list of dicts."""
        try:
            r = OpenPositions(self._account_id)
            self._client.request(r)
            result = []
            for pos in r.response.get("positions", []):
                long_units  = int(pos["long"]["units"])
                short_units = int(pos["short"]["units"])
                units = long_units if long_units != 0 else short_units
                if units != 0:
                    result.append({
                        "instrument": pos["instrument"],
                        "units":      units,
                        "side":       "long" if units > 0 else "short",
                        "unrealized_pl": float(pos.get("unrealizedPL", 0)),
                    })
            return result
        except Exception:
            logger.exception("Failed to fetch open OANDA positions")
            return []

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def submit_market_order(
        self, instrument: str, qty: float, side: str
    ) -> dict:
        """
        Submit a market order to OANDA.

        Args:
            instrument: OANDA instrument string (e.g. 'EUR_USD').
            qty:        Absolute unit count (always positive).
            side:       'buy' or 'sell'.

        Returns:
            Order result dict, or {} on failure.
        """
        units = int(qty) if side.lower() == "buy" else -int(qty)

        order_body = {
            "order": {
                "type":       "MARKET",
                "instrument": instrument.upper(),
                "units":      str(units),
            }
        }

        try:
            r = OrderCreate(self._account_id, data=order_body)
            self._client.request(r)
            fill = r.response.get("orderFillTransaction", {})
            result = {
                "id":         fill.get("id", ""),
                "instrument": fill.get("instrument", instrument),
                "units":      fill.get("units", str(units)),
                "price":      fill.get("price", ""),
                "status":     "filled" if fill else "pending",
            }
            logger.info(
                "OANDA order filled: %s %d units %s @ %s",
                side.upper(), abs(units), instrument, result.get("price", "?"),
            )
            return result
        except V20Error as e:
            logger.error("OANDA order rejected for %s: %s", instrument, e)
            return {}
        except Exception:
            logger.exception("Failed to submit OANDA order: %s %s", side, instrument)
            return {}

    def close_position(self, instrument: str) -> dict:
        """Close the entire open position for an instrument (long or short)."""
        try:
            pos = self.get_position(instrument)
            if not pos:
                logger.warning("close_position: no open position for %s", instrument)
                return {}
            data = {"longUnits": "ALL"} if pos["side"] == "long" else {"shortUnits": "ALL"}
            r = PositionClose(self._account_id, instrument.upper(), data=data)
            self._client.request(r)
            txn_ids = r.response.get("relatedTransactionIDs", [])
            logger.info("Closed OANDA position: %s", instrument)
            return {"id": txn_ids[0] if txn_ids else "", "status": "closed"}
        except V20Error as e:
            logger.error("OANDA close position failed for %s: %s", instrument, e)
            return {}
        except Exception:
            logger.exception("Failed to close OANDA position for %s", instrument)
            return {}
