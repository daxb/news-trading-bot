"""
FinBERT sentiment scoring for the Macro Trader bot.

Classifies financial text as positive / negative / neutral with a
confidence score. Model loads once at construction; call score() or
score_article() per article.
"""

import logging
import time

from transformers import pipeline

# Suppress noisy "unauthenticated requests" warning from huggingface_hub
logging.getLogger("huggingface_hub.utils._http").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

_MODEL_ID = "ProsusAI/finbert"
_MAX_CHARS = 2000  # ~500 tokens; BERT hard limit is 512 tokens

_SAFE_DEFAULT = {"label": "neutral", "score": 0.0}


def _build_text(article: dict) -> str:
    """Join headline + summary into a single string for scoring."""
    headline = (article.get("headline") or "").strip()
    summary = (article.get("summary") or "").strip()
    parts = [p for p in (headline, summary) if p]
    return " ".join(parts)


class SentimentAnalyzer:
    """Thin wrapper around the ProsusAI/finbert pipeline."""

    def __init__(self) -> None:
        start = time.monotonic()
        logger.info("Loading FinBERT model '%s' (first run downloads ~440 MB) …", _MODEL_ID)
        try:
            self._pipe = pipeline(
                "text-classification",
                model=_MODEL_ID,
                truncation=True,
                max_length=512,
            )
            elapsed = time.monotonic() - start
            logger.info("FinBERT loaded in %.1f s", elapsed)
        except Exception:
            logger.exception("Failed to load FinBERT model '%s'", _MODEL_ID)
            raise

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(self, text: str) -> dict:
        """
        Score a single string.

        Returns:
            {"label": "positive"|"negative"|"neutral", "score": float}
            {"label": "neutral", "score": 0.0} on empty input or error.
        """
        if not text or not text.strip():
            return _SAFE_DEFAULT.copy()

        try:
            result = self._pipe(text[:_MAX_CHARS])[0]
            return {
                "label": result["label"].lower(),
                "score": round(float(result["score"]), 4),
            }
        except Exception:
            logger.exception("FinBERT scoring failed for text (first 80 chars): %.80s", text)
            return _SAFE_DEFAULT.copy()

    def score_article(self, article: dict) -> dict:
        """
        Score a news article dict (as returned by core/news.py).

        Returns a *new* dict with the original keys intact plus:
            sentiment_label: "positive" | "negative" | "neutral"
            sentiment_score: float in [0.0, 1.0]
        """
        text = _build_text(article)
        result = self.score(text)
        return {
            **article,
            "sentiment_label": result["label"],
            "sentiment_score": result["score"],
        }

    def score_articles(self, articles: list[dict]) -> list[dict]:
        """
        Score a batch of articles in a single FinBERT forward pass.

        Roughly 3-5× faster than calling score_article() individually because
        the tokenizer and model run once over a padded batch instead of N
        separate calls. Falls back to per-article scoring on pipeline error.
        """
        if not articles:
            return []

        texts = [_build_text(a)[:_MAX_CHARS] for a in articles]

        # Identify non-empty texts; empty ones keep the safe default.
        non_empty = [(i, t) for i, t in enumerate(texts) if t.strip()]
        scored: list[dict] = [_SAFE_DEFAULT.copy() for _ in articles]

        if non_empty:
            indices, batch_texts = zip(*non_empty)
            try:
                raw = self._pipe(list(batch_texts), batch_size=16)
                for i, r in zip(indices, raw):
                    scored[i] = {
                        "label": r["label"].lower(),
                        "score": round(float(r["score"]), 4),
                    }
            except Exception:
                logger.exception(
                    "FinBERT batch scoring failed — falling back to per-article scoring"
                )
                for i, t in zip(indices, batch_texts):
                    scored[i] = self.score(t)

        return [
            {**article, "sentiment_label": r["label"], "sentiment_score": r["score"]}
            for article, r in zip(articles, scored)
        ]
