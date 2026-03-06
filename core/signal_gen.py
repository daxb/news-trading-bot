"""
Rule-based signal generator for the Macro Trader bot.

Takes a scored article (from sentiment.py) and applies a prioritised
rule table to produce a trading signal, or None if no rule fires or
confidence is below the configured threshold.

Design decisions
----------------
- Rule-based (no ML) for MVP: transparent and debuggable
- Single ticker per signal (SPY for all equity rules at MVP stage)
- First-matching rule wins (rules are ordered by priority)
- "hold" actions are suppressed — no signal returned, nothing stored
- Confidence = sentiment_score × rule confidence_multiplier

Signal dict schema
------------------
{
    "article_id":  int,
    "ticker":      str,
    "action":      "buy" | "sell",
    "confidence":  float,          # [0.0, 1.0]
    "theme":       str,
    "rationale":   str,
}
"""

import logging

from config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rule table — ordered by priority (most reliable / highest-impact first)
# ---------------------------------------------------------------------------
# Each rule:
#   theme               – machine-readable label stored with the signal
#   keywords            – lowercase substrings; ANY match fires the rule
#   actions             – maps FinBERT label → trade action or None (skip)
#   confidence_mult     – scales raw sentiment_score; lower = noisier theme
#   ticker              – instrument to trade
#   description         – used to build the human-readable rationale

_RULES: list[dict] = [
    {
        "theme": "fed_hawkish",
        "keywords": [
            "rate hike", "raises rates", "rate increase", "tightening",
            "hawkish", "restrictive policy", "quantitative tightening",
        ],
        "actions": {"positive": "sell", "negative": "sell", "neutral": None},
        "confidence_mult": 1.0,
        "ticker": "SPY",
        "description": "Fed tightening is bearish for equities",
    },
    {
        "theme": "fed_dovish",
        "keywords": [
            "rate cut", "cuts rates", "rate decrease", "easing",
            "dovish", "pivot", "pause", "quantitative easing",
        ],
        "actions": {"positive": "buy", "negative": None, "neutral": None},
        "confidence_mult": 1.0,
        "ticker": "SPY",
        "description": "Fed easing is bullish for equities",
    },
    {
        "theme": "jobs_strong",
        "keywords": [
            "jobs report", "nonfarm payroll", "payrolls beat",
            "unemployment falls", "hiring surge", "strong employment",
        ],
        "actions": {"positive": "buy", "negative": "sell", "neutral": None},
        "confidence_mult": 0.9,
        "ticker": "SPY",
        "description": "Jobs data drives growth expectations",
    },
    {
        "theme": "inflation",
        "keywords": [
            "inflation", "cpi", "price surge", "cost of living",
            "price index", "inflationary", "consumer prices",
        ],
        "actions": {"positive": None, "negative": "sell", "neutral": None},
        "confidence_mult": 0.85,
        "ticker": "SPY",
        "description": "High inflation pressures equities via rate-hike risk",
    },
    {
        "theme": "recession_risk",
        "keywords": [
            "recession", "downturn", "contraction", "gdp falls",
            "economic slowdown", "growth fears", "negative growth",
        ],
        "actions": {"positive": None, "negative": "sell", "neutral": None},
        "confidence_mult": 0.85,
        "ticker": "SPY",
        "description": "Recession signals are bearish for equities",
    },
    {
        "theme": "geopolitical_risk",
        "keywords": [
            "war", "conflict", "sanctions", "military strike",
            "invasion", "geopolitical", "escalation", "attack",
        ],
        "actions": {"positive": None, "negative": "sell", "neutral": None},
        "confidence_mult": 0.75,
        "ticker": "SPY",
        "description": "Geopolitical shocks trigger risk-off selling",
    },
    {
        "theme": "market_rally",
        "keywords": [
            "rally", "surges", "record high", "bull market",
            "all-time high", "stocks climb", "equities rise",
        ],
        "actions": {"positive": "buy", "negative": None, "neutral": None},
        "confidence_mult": 0.65,
        "ticker": "SPY",
        "description": "Broad market momentum supports further upside",
    },

    # ------------------------------------------------------------------
    # Forex rules (OANDA instruments)
    # ------------------------------------------------------------------
    {
        "theme": "usd_strength",
        "keywords": [
            "dollar surges", "dollar rises", "dollar strengthens",
            "usd rally", "strong dollar", "dollar dominance",
            "dollar index rises", "dxy rises",
        ],
        "actions": {"positive": "sell", "negative": "buy", "neutral": None},
        "confidence_mult": 0.80,
        "ticker": "EUR_USD",
        "description": "Strong USD is bearish for EUR/USD",
    },
    {
        "theme": "usd_weakness",
        "keywords": [
            "dollar falls", "dollar weakens", "dollar drops",
            "weak dollar", "dollar selloff", "dollar index falls", "dxy falls",
        ],
        "actions": {"positive": "buy", "negative": "sell", "neutral": None},
        "confidence_mult": 0.80,
        "ticker": "EUR_USD",
        "description": "Weak USD is bullish for EUR/USD",
    },
    {
        "theme": "gold_safe_haven",
        "keywords": [
            "gold rises", "gold surges", "gold rally", "gold hits",
            "safe haven demand", "flight to gold", "bullion rises",
        ],
        "actions": {"positive": "buy", "negative": "sell", "neutral": None},
        "confidence_mult": 0.75,
        "ticker": "XAU_USD",
        "description": "Safe-haven demand drives gold higher",
    },
    {
        "theme": "oil_demand",
        "keywords": [
            "oil rises", "crude rises", "oil prices surge", "crude rally",
            "opec cuts", "supply cut", "oil demand", "energy prices rise",
        ],
        "actions": {"positive": "buy", "negative": "sell", "neutral": None},
        "confidence_mult": 0.75,
        "ticker": "BCO_USD",
        "description": "Supply constraints or demand surge drives crude higher",
    },
]


def _build_text(article: dict) -> str:
    """Concatenate headline + summary for keyword matching."""
    headline = (article.get("headline") or "").strip()
    summary = (article.get("summary") or "").strip()
    return " ".join(p for p in (headline, summary) if p).lower()


class SignalGenerator:
    """Maps scored articles to trading signals via a priority rule table."""

    def __init__(self, conviction_threshold: float | None = None) -> None:
        self._threshold = (
            conviction_threshold
            if conviction_threshold is not None
            else settings.SIGNAL_CONVICTION_THRESHOLD
        )
        logger.info(
            "SignalGenerator ready (conviction_threshold=%.2f, rules=%d)",
            self._threshold, len(_RULES),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_relevant(self, article: dict) -> bool:
        """Return True if the article matches at least one rule's keywords.

        Used as a cheap pre-filter before FinBERT scoring so irrelevant
        articles never reach the GPU/CPU-intensive sentiment model.
        """
        text = _build_text(article)
        return any(
            any(kw in text for kw in rule["keywords"])
            for rule in _RULES
        )

    def classify_theme(self, text: str) -> tuple[str, float] | tuple[None, float]:
        """
        Return the first matching (theme_name, confidence_multiplier) or
        (None, 0.0) if no rule's keywords appear in the text.
        """
        lower = text.lower()
        for rule in _RULES:
            if any(kw in lower for kw in rule["keywords"]):
                return rule["theme"], rule["confidence_mult"]
        return None, 0.0

    def generate_signal(self, article: dict) -> dict | None:
        """
        Produce a trading signal from a scored article.

        Returns None when:
        - No rule matches the article text
        - The matched rule has no action for this sentiment direction
        - Computed confidence is below the conviction threshold
        """
        text = _build_text(article)
        if not text:
            return None

        sentiment_label = article.get("sentiment_label", "neutral")
        sentiment_score = float(article.get("sentiment_score", 0.0))

        lower = text
        for rule in _RULES:
            if not any(kw in lower for kw in rule["keywords"]):
                continue

            action = rule["actions"].get(sentiment_label)
            if not action:
                logger.debug(
                    "Rule '%s' matched but no action for sentiment '%s' — skipping",
                    rule["theme"], sentiment_label,
                )
                return None

            confidence = round(sentiment_score * rule["confidence_mult"], 4)
            if confidence < self._threshold:
                logger.debug(
                    "Rule '%s' fired but confidence %.4f < threshold %.4f — skipping",
                    rule["theme"], confidence, self._threshold,
                )
                return None

            signal = {
                "article_id": article.get("id"),
                "ticker": rule["ticker"],
                "action": action,
                "confidence": confidence,
                "theme": rule["theme"],
                "rationale": (
                    f"{sentiment_label.capitalize()} sentiment "
                    f"({sentiment_score:.2f}) on '{rule['theme']}' → "
                    f"{action.upper()} {rule['ticker']}: {rule['description']}"
                ),
            }
            logger.info(
                "Signal: %s %s | theme=%s | confidence=%.4f",
                action.upper(), rule["ticker"], rule["theme"], confidence,
            )
            return signal

        logger.debug("No rule matched article id=%s", article.get("id"))
        return None

    def generate_signals(self, articles: list[dict]) -> list[dict]:
        """Batch wrapper — returns only non-None signals."""
        signals = []
        for article in articles:
            signal = self.generate_signal(article)
            if signal is not None:
                signals.append(signal)
        logger.debug(
            "generate_signals: %d articles → %d signals", len(articles), len(signals)
        )
        return signals
