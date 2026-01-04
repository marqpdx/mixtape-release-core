"""
Cross-Encoder Re-ranking for Search Results

Provides high-accuracy re-ranking of top search results using cross-encoder models.

Cross-encoders are more accurate than bi-encoders (semantic embeddings) because they
process the query and document together, but they're much slower. We use them only
for re-ranking the top K results from the initial retrieval.

Two-stage retrieval flow:
1. Fast first-pass: Hybrid search (semantic + BM25) retrieves top N candidates
2. Slow second-pass: Cross-encoder re-ranks top K results (K < N)

Usage:
    results = [...initial hybrid search results...]
    reranked = rerank_results(
        query="yoga practices energy",
        results=results[:20],  # Re-rank top 20
    )
"""

import logging
from typing import List, Dict, Any
from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)

# Global cross-encoder instance (lazy-loaded)
_cross_encoder = None


def get_cross_encoder() -> CrossEncoder:
    """
    Get the global cross-encoder model instance.

    Uses ms-marco-MiniLM-L-6-v2:
    - 384 dimensions
    - Trained on MS MARCO passage ranking dataset
    - Fast and effective for re-ranking

    Returns:
        CrossEncoder model instance
    """
    global _cross_encoder

    if _cross_encoder is None:
        logger.info("Loading cross-encoder model: cross-encoder/ms-marco-MiniLM-L-6-v2")

        # Force CPU to avoid MPS issues
        import os
        import torch

        # Disable MPS entirely - force CPU mode
        os.environ['PYTORCH_ENABLE_MPS_FALLBACK'] = '0'

        # Set PyTorch default device to CPU before loading model
        original_device = torch.get_default_device() if hasattr(torch, 'get_default_device') else None
        torch.set_default_device('cpu')

        try:
            # Load cross-encoder with CPU as default device
            _cross_encoder = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
        finally:
            # Restore original default device if it was set
            if original_device is not None:
                torch.set_default_device(original_device)

        logger.info("Cross-encoder model loaded successfully")

    return _cross_encoder


def rerank_results(
    query: str,
    results: List[Dict[str, Any]],
    top_k: int = None,
) -> List[Dict[str, Any]]:
    """
    Re-rank search results using a cross-encoder model.

    Args:
        query: Search query text
        results: List of result dicts (must have 'text' and 'score' keys)
        top_k: Number of results to re-rank (default: all results)
               Note: Re-ranking is expensive, typically apply to top 10-20

    Returns:
        Re-ranked results (same format as input, with updated 'score' values)
    """
    if not results:
        return results

    # Determine how many to re-rank
    if top_k is None:
        top_k = len(results)
    else:
        top_k = min(top_k, len(results))

    # Get cross-encoder model
    try:
        model = get_cross_encoder()
    except Exception as e:
        logger.error(f"Failed to load cross-encoder: {e}")
        # Return original results if re-ranking fails
        return results

    # Prepare query-document pairs for the top_k results
    pairs = [
        [query, result["text"]]
        for result in results[:top_k]
    ]

    try:
        # Get cross-encoder scores
        # These are relevance scores (higher = more relevant)
        cross_scores = model.predict(pairs)

        # Update scores for re-ranked results
        for i, score in enumerate(cross_scores):
            results[i]["score"] = float(score)

        # Re-sort by new scores (descending)
        results[:top_k] = sorted(
            results[:top_k],
            key=lambda x: x["score"],
            reverse=True,
        )

        logger.debug(f"Re-ranked top {top_k} results using cross-encoder")

    except Exception as e:
        logger.error(f"Cross-encoder prediction failed: {e}")
        # Return original results if prediction fails
        return results

    return results


def rerank_with_threshold(
    query: str,
    results: List[Dict[str, Any]],
    top_k: int = 20,
    min_score: float = 0.0,
) -> List[Dict[str, Any]]:
    """
    Re-rank results and filter by minimum score threshold.

    Args:
        query: Search query text
        results: List of result dicts
        top_k: Number of results to re-rank
        min_score: Minimum cross-encoder score to include (default: 0.0)

    Returns:
        Re-ranked and filtered results
    """
    # Re-rank top K
    reranked = rerank_results(query, results, top_k)

    # Filter by threshold
    filtered = [
        result for result in reranked
        if result["score"] >= min_score
    ]

    return filtered
