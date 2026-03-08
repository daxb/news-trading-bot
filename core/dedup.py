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
    # General English
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "has", "have", "had", "as", "it", "its", "that", "this", "his", "her",
    "their", "he", "she", "they", "we", "you", "i", "my", "our", "new",
    "says", "said", "say", "report", "reports", "amid", "over", "after",
    "more", "than", "up", "down", "out", "into", "about", "will", "would",
    "could", "may", "not", "no", "what", "how", "when", "where", "who",
    # Financial — generic action verbs that appear in many unrelated headlines
    "surge", "surges", "rally", "rallies", "slump", "slumps",
    "slide", "slides", "jump", "jumps", "plunge", "plunges",
    "dive", "dives", "soar", "soars", "tumble", "tumbles",
    "rise", "rises", "fall", "falls", "drop", "drops", "hit", "hits",
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
    Remove articles whose headline is too similar to one already seen,
    while tracking in-batch source corroboration.

    When two articles in the same batch cover the same story (Jaccard ≥ threshold)
    but come from different sources, the second article is dropped as a duplicate
    but its source is recorded on the first article's ``source_count`` field.
    This allows the signal generator to know how many independent sources
    confirmed the story within a single poll cycle.

    Articles that match a DB headline are dropped unconditionally (already processed).

    Args:
        articles:        Incoming articles to filter (already ID-deduped).
        seen_headlines:  Headlines from the DB for the recent window.
        threshold:       Jaccard threshold (defaults to DEDUP_SIMILARITY_THRESHOLD).

    Returns:
        Accepted articles, each with an added ``source_count`` int field.
    """
    if threshold is None:
        threshold = settings.DEDUP_SIMILARITY_THRESHOLD

    # Pre-tokenize DB headlines (no source info — pure duplicate suppression)
    db_tokens: list[frozenset[str]] = [_tokenize(h) for h in seen_headlines if h]

    accepted: list[dict] = []
    # Parallel tracking structures for in-batch comparison
    accepted_tokens: list[frozenset[str]] = []
    accepted_sources: list[set[str]] = []   # distinct sources per accepted article

    dropped = 0

    for article in articles:
        headline = article.get("headline", "")
        source = article.get("source") or ""

        if not headline:
            accepted.append({**article, "source_count": 1})
            accepted_tokens.append(frozenset())
            accepted_sources.append({source})
            continue

        candidate = _tokenize(headline)

        # 1. Drop if it matches a DB headline (already processed last cycle)
        if any(_jaccard(candidate, seen) >= threshold for seen in db_tokens):
            logger.debug("Dedup (DB): dropped '%s'", headline[:80])
            dropped += 1
            continue

        # 2. Check against in-batch accepted articles
        matched_idx: int | None = None
        for i, acc_tokens in enumerate(accepted_tokens):
            if _jaccard(candidate, acc_tokens) >= threshold:
                matched_idx = i
                break

        if matched_idx is not None:
            # Near-duplicate of an already-accepted article in this batch.
            # If it's from a different source, record the corroboration.
            if source and source not in accepted_sources[matched_idx]:
                accepted_sources[matched_idx].add(source)
                new_count = len(accepted_sources[matched_idx])
                accepted[matched_idx] = {
                    **accepted[matched_idx],
                    "source_count": new_count,
                }
                logger.debug(
                    "Dedup: corroborated '%s' via '%s' (sources=%d)",
                    headline[:60], source, new_count,
                )
            else:
                logger.debug("Dedup: dropped same-source duplicate '%s'", headline[:80])
            dropped += 1
        else:
            # Unique article — accept and track
            accepted.append({**article, "source_count": 1})
            accepted_tokens.append(candidate)
            accepted_sources.append({source} if source else set())

    if dropped:
        logger.info(
            "Dedup: %d articles in → %d accepted, %d dropped",
            len(articles), len(accepted), dropped,
        )

    return accepted
