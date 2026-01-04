"""
BM25 Keyword Scoring for Hybrid Search

Provides BM25 (Best Matching 25) scoring to complement semantic vector search.
BM25 is a probabilistic retrieval function that ranks documents based on term frequency
and inverse document frequency.

Usage:
    chunks = Chunk.objects.filter(...)
    bm25_scores = calculate_bm25_scores(
        query="yoga practices energy",
        chunks=chunks,
    )
    # Returns: {chunk_id: bm25_score, ...}
"""

import re
from typing import Dict, List
from rank_bm25 import BM25Okapi


def tokenize(text: str) -> List[str]:
    """
    Simple tokenization for BM25.

    Args:
        text: Text to tokenize

    Returns:
        List of lowercase tokens
    """
    # Convert to lowercase and split on non-alphanumeric
    tokens = re.findall(r'\b\w+\b', text.lower())
    return tokens


def calculate_bm25_scores(
    query: str,
    chunks: List,  # List of Chunk objects
) -> Dict[str, float]:
    """
    Calculate BM25 scores for chunks against a query.

    BM25 parameters:
    - k1: Controls term frequency saturation (default: 1.5)
    - b: Controls document length normalization (default: 0.75)

    Args:
        query: Search query text
        chunks: List of Chunk model instances

    Returns:
        Dict mapping chunk_id (str) -> bm25_score (float)
        Scores are normalized to [0, 1] range for easy combining with semantic scores
    """
    if not chunks:
        return {}

    # Build corpus (tokenized chunk texts)
    corpus = []
    chunk_ids = []

    for chunk in chunks:
        corpus.append(tokenize(chunk.text))
        chunk_ids.append(str(chunk.id))

    # Initialize BM25
    bm25 = BM25Okapi(corpus)

    # Tokenize query
    query_tokens = tokenize(query)

    # Get BM25 scores
    raw_scores = bm25.get_scores(query_tokens)

    # Normalize scores to [0, 1] range
    # BM25 scores are unbounded, so we use min-max normalization
    max_score = max(raw_scores) if max(raw_scores) > 0 else 1.0
    min_score = min(raw_scores)
    score_range = max_score - min_score

    if score_range == 0:
        # All scores are the same - normalize to 0.5
        normalized_scores = [0.5] * len(raw_scores)
    else:
        normalized_scores = [
            (score - min_score) / score_range
            for score in raw_scores
        ]

    # Build result dict
    result = {
        chunk_id: score
        for chunk_id, score in zip(chunk_ids, normalized_scores)
    }

    return result


def combine_scores(
    semantic_score: float,
    bm25_score: float,
    semantic_weight: float = 0.7,
    bm25_weight: float = 0.3,
) -> float:
    """
    Combine semantic and BM25 scores using weighted average.

    Args:
        semantic_score: Cosine similarity score from Qdrant (0-1)
        bm25_score: Normalized BM25 score (0-1)
        semantic_weight: Weight for semantic score (default: 0.7)
        bm25_weight: Weight for BM25 score (default: 0.3)

    Returns:
        Combined score (0-1)
    """
    return (semantic_weight * semantic_score) + (bm25_weight * bm25_score)
