"""
Macro context filter for the Macro Trader bot.

Fetches key FRED indicators (Fed rate, unemployment, 10-yr yield) and uses
them to adjust signal confidence before execution. Signals whose confidence
falls below SIGNAL_CONVICTION_THRESHOLD after adjustment are dropped.

Rationale
---------
A "fed_dovish" headline means little if rates are already near zero — there's
nowhere to cut. Macro context turns the signal engine from pure text matching
into something regime-aware: the same headline carries different weight
depending on current economic conditions.

Refresh cadence
---------------
FRED data is published monthly/weekly — there's no value in re-fetching every
5 minutes. MacroContext refreshes every MACRO_REFRESH_CYCLES poll cycles
(default 12 × 5 min = ~1 hour).
"""

import logging

from config import settings
from core.macro import MacroClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-theme multiplier rules
# Each entry: (indicator_key, condition_fn, multiplier, description)
# ---------------------------------------------------------------------------
_RULES: list[tuple] = [
    # Fed Funds Rate
    ("FEDFUNDS", lambda v: v > settings.FEDFUNDS_HIGH, 1.2, "fed_hawkish", "high rates confirm tightening thesis"),
    ("FEDFUNDS", lambda v: v < settings.FEDFUNDS_LOW,  0.6, "fed_hawkish", "rates too low for credible tightening"),
    ("FEDFUNDS", lambda v: v > settings.FEDFUNDS_HIGH, 1.2, "fed_dovish",  "elevated rates mean room to cut exists"),
    ("FEDFUNDS", lambda v: v < 1.5,                    0.6, "fed_dovish",  "rates near zero, limited room to cut"),
    # Unemployment Rate
    ("UNRATE",   lambda v: v > settings.UNRATE_HIGH,   1.2, "recession_risk", "elevated unemployment supports recession thesis"),
    ("UNRATE",   lambda v: v < settings.UNRATE_LOW,    0.7, "recession_risk", "tight labour market contradicts recession thesis"),
    ("UNRATE",   lambda v: v < settings.UNRATE_LOW,    1.2, "jobs_strong",    "tight labour market confirms jobs thesis"),
    ("UNRATE",   lambda v: v > settings.UNRATE_HIGH,   0.7, "jobs_strong",    "elevated unemployment contradicts jobs thesis"),
    # 10-Year Treasury Yield
    ("DGS10",    lambda v: v > settings.DGS10_HIGH,    1.1, "geopolitical_risk", "elevated yields confirm risk-off environment"),
    # Yield Curve (10Y − 2Y): inversion is a reliable recession leading indicator
    ("T10Y2Y",   lambda v: v < settings.T10Y2Y_INVERSION, 1.25, "recession_risk", "inverted yield curve confirms recession risk"),
    ("T10Y2Y",   lambda v: v < settings.T10Y2Y_INVERSION, 0.75, "jobs_strong",    "inverted yield curve contradicts jobs strength thesis"),
    ("T10Y2Y",   lambda v: v >= 0,                     0.85, "recession_risk", "non-inverted curve reduces recession probability"),
    # HY Credit Spreads: wide spreads = credit stress / risk-off
    ("BAMLH0A0HYM2", lambda v: v > settings.HY_SPREAD_HIGH, 1.2, "recession_risk",    "wide credit spreads confirm financial stress"),
    ("BAMLH0A0HYM2", lambda v: v > settings.HY_SPREAD_HIGH, 1.2, "geopolitical_risk", "wide credit spreads confirm risk-off environment"),
    ("BAMLH0A0HYM2", lambda v: v > settings.HY_SPREAD_HIGH, 0.7, "fed_dovish",        "credit stress makes easy financial conditions less likely"),
    # USD Trade-Weighted Index: strong USD affects forex signals
    ("DTWEXBGS", lambda v: v > settings.USD_INDEX_HIGH, 1.2, "usd_strength", "elevated USD index confirms dollar strength thesis"),
    ("DTWEXBGS", lambda v: v > settings.USD_INDEX_HIGH, 0.7, "usd_weakness", "elevated USD index contradicts dollar weakness thesis"),
    # Initial Jobless Claims: timely weekly labour market signal
    ("ICSA",     lambda v: v > settings.ICSA_HIGH,     1.2, "recession_risk", "elevated jobless claims support recession thesis"),
    ("ICSA",     lambda v: v > settings.ICSA_HIGH,     0.7, "jobs_strong",    "elevated jobless claims contradict jobs strength thesis"),
    # VIX: broad fear gauge; elevated VIX = risk-off
    ("VIXCLS",   lambda v: v > settings.VIX_HIGH,      1.2, "geopolitical_risk", "elevated VIX confirms risk-off/fear environment"),
    ("VIXCLS",   lambda v: v > settings.VIX_HIGH,      1.1, "recession_risk",    "elevated VIX supports risk-off thesis"),
    ("VIXCLS",   lambda v: v > settings.VIX_HIGH,      0.8, "market_rally",      "elevated VIX contradicts broad market rally thesis"),
]


class MacroContext:
    """Holds the current macro snapshot and applies it to signals."""

    def __init__(self, macro_client: MacroClient) -> None:
        self._macro = macro_client
        self._indicators: dict = {}
        self._poll_count: int = 0
        self.refresh()

    # ------------------------------------------------------------------
    # Data refresh
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Fetch the latest FRED indicators. Logs a snapshot summary."""
        self._indicators = self._macro.get_key_indicators()
        snapshot = {k: round(v["value"], 2) for k, v in self._indicators.items()}
        logger.info("Macro snapshot: %s", snapshot)

    def tick(self) -> None:
        """Call once per poll cycle — triggers a refresh when due."""
        self._poll_count += 1
        if self._poll_count % settings.MACRO_REFRESH_CYCLES == 0:
            logger.info("Refreshing macro context (cycle %d) …", self._poll_count)
            self.refresh()

    # ------------------------------------------------------------------
    # Confidence adjustment
    # ------------------------------------------------------------------

    def _multiplier_for(self, theme: str) -> float:
        """
        Return the combined confidence multiplier for a signal theme.

        Iterates matching rules and multiplies their factors together.
        Returns 1.0 (no change) if no indicators are available.
        """
        multiplier = 1.0
        for indicator, condition, factor, rule_theme, description in _RULES:
            if rule_theme != theme:
                continue
            data = self._indicators.get(indicator)
            if not data:
                continue
            value = data["value"]
            if condition(value):
                logger.debug(
                    "Macro adjustment: theme='%s' indicator=%s=%.2f → ×%.1f (%s)",
                    theme, indicator, value, factor, description,
                )
                multiplier *= factor
        return round(multiplier, 4)

    def adjust_signals(self, signals: list[dict]) -> list[dict]:
        """
        Apply macro-adjusted confidence to each signal.

        Signals whose adjusted confidence falls below SIGNAL_CONVICTION_THRESHOLD
        are dropped. Returns only signals that survive the filter.
        """
        if not self._indicators:
            logger.warning("No macro indicators loaded — passing signals through unadjusted")
            return signals

        adjusted: list[dict] = []
        for sig in signals:
            theme = sig.get("theme", "")
            original_confidence = sig["confidence"]
            multiplier = self._multiplier_for(theme)
            new_confidence = round(original_confidence * multiplier, 4)

            if new_confidence < settings.SIGNAL_CONVICTION_THRESHOLD:
                logger.info(
                    "Signal dropped by macro filter: theme=%s confidence %.4f × %.2f = %.4f < threshold %.2f",
                    theme, original_confidence, multiplier, new_confidence,
                    settings.SIGNAL_CONVICTION_THRESHOLD,
                )
                continue

            if multiplier != 1.0:
                logger.info(
                    "Macro-adjusted confidence: theme=%s %.4f → %.4f (×%.2f)",
                    theme, original_confidence, new_confidence, multiplier,
                )

            adjusted.append({**sig, "confidence": new_confidence})

        logger.debug(
            "Macro filter: %d signals in → %d signals out", len(signals), len(adjusted)
        )
        return adjusted
