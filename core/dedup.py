"""
Headline-similarity deduplication for the Macro Trader bot.

Catches cross-source duplicates that share the same story but have
different URLs (and therefore different article IDs). Uses Jaccard
similarity on tokenized headlines — no extra dependencies required.

How it works
------------
1. Tokenize each headline: lowercase, strip punctuation, remove stopwords
2. For each incoming article, compare its token set against all "seen"
   headlines (recent DB headlines + earlier articles in the same batch)
3. If Jaccard similarity >= threshold, the article is a duplicate → skip
4. Otherwise accept it and add its headline to the seen set

Jaccard similarity = |A ∩ B| / |A ∪ B|

A threshold of 0.5 means "half the unique words overlap" — tight enough
to avoid false positives on topically similar but distinct stories, loose
enough to catch the same event reported with slightly different wording.
"""

import logging
import re
import string

from config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stopwords — common English words that add noise to headline comparisons
# ---------------------------------------------------------------------------
_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "has", "have", "had", "as", "it", "its", "that", "this", "his", "her",
    "their", "he", "she", "they", "we", "you", "i", "my", "our", "new",
    "says", "said", "say", "report", "reports", "amid", "over", "after",
    "more", "than", "up", "down", "out", "into", "about", "will", "would",
    "could", "may", "not", "no", "what", "how", "when", "where", "who",
})


def _tokenize(text: str) -> frozenset[str]:
    """Lowercase, strip punctuation, remove stopwords and short tokens."""
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    tokens = text.split()
    return frozenset(t for t in tokens if t not in _STOPWORDS and len(t) > 2)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard similarity between two token sets. Returns 0.0 if both empty."""
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def deduplicate(
    articles: list[dict],
    seen_headlines: list[str],
    threshold: float | None = None,
) -> list[dict]:
    """
    Remove articles whose headline is too similar to one already seen.

    Args:
        articles:        Incoming articles to filter (already ID-deduped).
        seen_headlines:  Headlines from the DB for the recent window.
        threshold:       Jaccard threshold (defaults to DEDUP_SIMILARITY_THRESHOLD).

    Returns:
        Filtered list with near-duplicate articles removed.
    """
    if threshold is None:
        threshold = settings.DEDUP_SIMILARITY_THRESHOLD

    # Pre-tokenize all seen headlines
    seen_tokens: list[frozenset[str]] = [_tokenize(h) for h in seen_headlines if h]

    accepted: list[dict] = []
    dropped = 0

    for article in articles:
        headline = article.get("headline", "")
        if not headline:
            accepted.append(article)
            continue

        candidate = _tokenize(headline)

        # Compare against all seen headlines
        is_duplicate = False
        for seen in seen_tokens:
            if _jaccard(candidate, seen) >= threshold:
                is_duplicate = True
                break

        if is_duplicate:
            logger.debug("Dedup: dropped near-duplicate '%s'", headline[:80])
            dropped += 1
        else:
            accepted.append(article)
            seen_tokens.append(candidate)  # add to seen for in-batch dedup

    if dropped:
        logger.info(
            "Dedup: %d articles in → %d accepted, %d near-duplicates dropped",
            len(articles), len(accepted), dropped,
        )

    return accepted
