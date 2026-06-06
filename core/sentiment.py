"""
FinBERT sentiment scoring for the Macro Trader bot.

Classifies financial text as positive / negative / neutral with a confidence
score. Runs the ProsusAI/finbert model via ONNX Runtime (CPU) — deliberately
torch-free at runtime so the heavy libtorch runtime never loads (~227 MB less
RSS than the transformers/torch pipeline; lets the Fly VM sit at 1 GB). The
fp32 ONNX export is numerically identical to torch — labels and scores match to
4 decimals — so this is a pure footprint change with no signal drift.

The model directory (model.onnx + tokenizer.json + config.json) is exported and
baked into the image by the Dockerfile; see settings.FINBERT_ONNX_DIR.
"""

import json
import logging
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from config import settings

logger = logging.getLogger(__name__)

_MAX_CHARS = 2000  # ~500 tokens; BERT hard limit is 512 tokens
_MAX_TOKENS = 512

_SAFE_DEFAULT = {"label": "neutral", "score": 0.0}


def _build_text(article: dict) -> str:
    """Join headline + summary into a single string for scoring."""
    headline = (article.get("headline") or "").strip()
    summary = (article.get("summary") or "").strip()
    parts = [p for p in (headline, summary) if p]
    return " ".join(parts)


class SentimentAnalyzer:
    """Thin wrapper around the ProsusAI/finbert model running on ONNX Runtime."""

    def __init__(self, model_dir: str | None = None) -> None:
        model_dir = Path(model_dir or settings.FINBERT_ONNX_DIR)
        start = time.monotonic()
        logger.info("Loading FinBERT ONNX model from '%s' …", model_dir)
        try:
            cfg = json.loads((model_dir / "config.json").read_text())
            self._id2label = {int(k): v.lower() for k, v in cfg["id2label"].items()}

            self._tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
            self._tokenizer.enable_truncation(max_length=_MAX_TOKENS)
            self._tokenizer.enable_padding()

            self._session = ort.InferenceSession(
                str(model_dir / "model.onnx"),
                providers=["CPUExecutionProvider"],
            )
            self._input_names = {i.name for i in self._session.get_inputs()}

            elapsed = time.monotonic() - start
            logger.info("FinBERT ONNX loaded in %.1f s", elapsed)
        except Exception:
            logger.exception("Failed to load FinBERT ONNX model from '%s'", model_dir)
            raise

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def _infer(self, texts: list[str]) -> list[dict]:
        """Run a batch of texts through the ONNX session.

        Returns one {"label", "score"} dict per input text. Padding is masked by
        attention_mask so batched results match single-text scoring exactly.
        """
        encs = self._tokenizer.encode_batch(texts)
        feed = {
            "input_ids": np.array([e.ids for e in encs], dtype=np.int64),
            "attention_mask": np.array([e.attention_mask for e in encs], dtype=np.int64),
        }
        # FinBERT (BERT-base) also expects token_type_ids; include only if the
        # exported graph declares it.
        if "token_type_ids" in self._input_names:
            feed["token_type_ids"] = np.array([e.type_ids for e in encs], dtype=np.int64)

        logits = self._session.run(None, feed)[0]
        # Row-wise softmax (numerically stable).
        shifted = logits - logits.max(axis=1, keepdims=True)
        exp = np.exp(shifted)
        probs = exp / exp.sum(axis=1, keepdims=True)
        best = probs.argmax(axis=1)
        return [
            {"label": self._id2label[int(best[r])], "score": round(float(probs[r, best[r]]), 4)}
            for r in range(len(texts))
        ]

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
            return self._infer([text[:_MAX_CHARS]])[0]
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
        Score a batch of articles in a single ONNX forward pass.

        Roughly 3-5× faster than calling score_article() individually because
        the tokenizer and model run once over a padded batch instead of N
        separate calls. Falls back to per-article scoring on inference error.
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
                results = self._infer(list(batch_texts))
                for i, r in zip(indices, results):
                    scored[i] = r
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
