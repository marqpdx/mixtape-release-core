"""
Embedding Provider Interface

Provides a stable interface for embedding text, regardless of the underlying provider.

Supported providers:
- OpenAI (text-embedding-3-small, text-embedding-3-large, etc.)
- Local models (future)
- Custom FastAPI service (future)

Contract Rules:
- Model selection is explicit (via EmbeddingModel instance)
- Returned vector length MUST match embedding_model.dimensions
- Provider is determined by embedding_model.provider field

Batch Processing:
- OpenAI: Up to 2048 texts per API call (rate limits apply)
- Sentence-transformers: Configurable batch size (default 128)
- Automatic chunking for large inputs

Rate Limits (OpenAI):
- text-embedding-3-small: 1,000,000 TPM (tokens per minute)
- text-embedding-3-large: 1,000,000 TPM
- Exponential backoff on rate limit errors
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:
    from stackroom.models import EmbeddingModel

logger = logging.getLogger(__name__)

# Provider-specific batch sizes
OPENAI_MAX_BATCH_SIZE = 2048  # OpenAI API limit
SENTENCE_TRANSFORMERS_DEFAULT_BATCH_SIZE = 128  # Good balance for CPU/GPU

# Retry configuration for rate limits
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 1.0  # seconds
MAX_RETRY_DELAY = 60.0  # seconds


class EmbeddingProviderError(Exception):
    """Base exception for embedding provider errors"""

    pass


class DimensionMismatchError(EmbeddingProviderError):
    """Raised when returned embeddings have wrong dimensions"""

    pass


class RateLimitError(EmbeddingProviderError):
    """Raised when hitting provider rate limits"""

    pass


def embed_texts(
    texts: list[str],
    *,
    embedding_model: EmbeddingModel,
    batch_size: int | None = None,
) -> list[list[float]]:
    """
    Embed a list of texts using the specified embedding model.

    Automatically chunks large inputs into provider-appropriate batches:
    - OpenAI: 2048 texts per batch (API limit)
    - Sentence-transformers: 128 texts per batch (configurable)

    Args:
        texts: List of text strings to embed
        embedding_model: EmbeddingModel instance specifying model config
        batch_size: Optional batch size override (defaults to provider-specific)

    Returns:
        List of embedding vectors (list of floats)

    Raises:
        EmbeddingProviderError: If embedding fails
        DimensionMismatchError: If returned dimensions don't match model config
        RateLimitError: If rate limit exceeded after retries
    """
    if not texts:
        return []

    provider = embedding_model.provider.lower() if embedding_model.provider else "openai"

    # Determine batch size
    if batch_size is None:
        if provider == "openai":
            batch_size = OPENAI_MAX_BATCH_SIZE
        elif provider == "sentence-transformers":
            batch_size = SENTENCE_TRANSFORMERS_DEFAULT_BATCH_SIZE
        else:
            batch_size = 100  # Default for unknown providers

    # Process in batches if input is large
    if len(texts) <= batch_size:
        # Single batch - process directly
        return _embed_provider(texts, embedding_model=embedding_model, provider=provider)
    else:
        # Multiple batches - chunk and process
        all_vectors = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            vectors = _embed_provider(batch, embedding_model=embedding_model, provider=provider)
            all_vectors.extend(vectors)

        logger.info(
            f"Processed {len(texts)} texts in {(len(texts) + batch_size - 1) // batch_size} batches "
            f"(batch_size={batch_size})"
        )

        return all_vectors


def _embed_provider(
    texts: list[str],
    *,
    embedding_model: EmbeddingModel,
    provider: str,
) -> list[list[float]]:
    """
    Route to the appropriate provider implementation.

    Args:
        texts: List of text strings
        embedding_model: EmbeddingModel instance
        provider: Provider name (openai, sentence-transformers, local)

    Returns:
        List of embedding vectors

    Raises:
        EmbeddingProviderError: If provider is unsupported or embedding fails
    """
    if provider == "openai":
        return _embed_openai(texts, embedding_model=embedding_model)
    elif provider == "local":
        return _embed_local(texts, embedding_model=embedding_model)
    elif provider == "sentence-transformers":
        return _embed_sentence_transformers(texts, embedding_model=embedding_model)
    else:
        raise EmbeddingProviderError(
            f"Unsupported embedding provider: {provider}. "
            f"Supported: openai, local, sentence-transformers"
        )


def _embed_openai(
    texts: list[str],
    *,
    embedding_model: EmbeddingModel,
) -> list[list[float]]:
    """
    Embed texts using OpenAI's embedding API with exponential backoff.

    Batch Processing:
    - OpenAI supports up to 2048 texts per API call
    - Input is automatically chunked if larger

    Rate Limits:
    - text-embedding-3-small: 1,000,000 TPM
    - text-embedding-3-large: 1,000,000 TPM
    - Implements exponential backoff on rate limit errors

    Args:
        texts: List of text strings (up to 2048)
        embedding_model: EmbeddingModel instance

    Returns:
        List of embedding vectors

    Raises:
        EmbeddingProviderError: If API call fails after retries
        DimensionMismatchError: If dimensions don't match
        RateLimitError: If rate limit exceeded after max retries
    """
    try:
        from openai import OpenAI, RateLimitError as OpenAIRateLimitError
    except ImportError:
        raise EmbeddingProviderError(
            "OpenAI package not installed. Install with: pip install openai"
        )

    api_key = getattr(settings, "OPENAI_API_KEY", None)
    if not api_key:
        raise EmbeddingProviderError(
            "OPENAI_API_KEY not configured in settings"
        )

    client = OpenAI(api_key=api_key)

    # Exponential backoff retry logic
    retry_delay = INITIAL_RETRY_DELAY
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            # Call OpenAI embeddings API
            response = client.embeddings.create(
                model=embedding_model.name,
                input=texts,
            )

            # Extract vectors
            vectors = [item.embedding for item in response.data]

            # Validate dimensions
            for i, vector in enumerate(vectors):
                if len(vector) != embedding_model.dimensions:
                    raise DimensionMismatchError(
                        f"Vector {i} has {len(vector)} dimensions, "
                        f"expected {embedding_model.dimensions}"
                    )

            logger.info(
                f"Embedded {len(texts)} texts using OpenAI {embedding_model.name}"
            )

            return vectors

        except OpenAIRateLimitError as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                logger.warning(
                    f"OpenAI rate limit hit (attempt {attempt + 1}/{MAX_RETRIES}), "
                    f"retrying in {retry_delay:.1f}s..."
                )
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY)
            else:
                logger.error(
                    f"OpenAI rate limit exceeded after {MAX_RETRIES} attempts"
                )
                raise RateLimitError(
                    f"OpenAI rate limit exceeded after {MAX_RETRIES} retries"
                ) from e

        except Exception as e:
            if isinstance(e, (EmbeddingProviderError, DimensionMismatchError)):
                raise
            logger.error(f"OpenAI embedding error: {e}")
            raise EmbeddingProviderError(f"OpenAI API error: {str(e)}") from e

    # Should not reach here, but just in case
    raise RateLimitError(
        f"OpenAI rate limit exceeded after {MAX_RETRIES} retries"
    ) from last_error


def _embed_sentence_transformers(
    texts: list[str],
    *,
    embedding_model: EmbeddingModel,
) -> list[list[float]]:
    """
    Embed texts using sentence-transformers local models.

    Args:
        texts: List of text strings
        embedding_model: EmbeddingModel instance

    Returns:
        List of embedding vectors

    Raises:
        EmbeddingProviderError: If model loading or inference fails
        DimensionMismatchError: If dimensions don't match
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise EmbeddingProviderError(
            "sentence-transformers package not installed. "
            "Install with: pip install sentence-transformers"
        )

    try:
        # Force CPU usage to avoid MPS issues on Apple Silicon
        import os
        import torch

        # Disable MPS entirely - force CPU mode
        os.environ['PYTORCH_ENABLE_MPS_FALLBACK'] = '0'

        # CRITICAL: Set PyTorch default device to CPU BEFORE loading model
        # sentence-transformers 4.1.0 doesn't always respect device parameter on first load
        if hasattr(torch, 'set_default_device'):
            torch.set_default_device('cpu')

        # Also set default tensor type to CPU
        torch.set_default_tensor_type(torch.FloatTensor)

        # Load model - will use CPU by default now
        model = SentenceTransformer(embedding_model.name)

        # Explicitly move to CPU (belt and suspenders)
        model = model.to('cpu')

        # Generate embeddings
        embeddings = model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=embedding_model.normalize,
            show_progress_bar=False,  # Disable tqdm to avoid threading issues
        )

        # Convert to list of lists
        vectors = embeddings.tolist()

        # Validate dimensions
        for i, vector in enumerate(vectors):
            if len(vector) != embedding_model.dimensions:
                raise DimensionMismatchError(
                    f"Vector {i} has {len(vector)} dimensions, "
                    f"expected {embedding_model.dimensions}"
                )

        logger.info(
            f"Embedded {len(texts)} texts using sentence-transformers {embedding_model.name}"
        )

        return vectors

    except Exception as e:
        if isinstance(e, (EmbeddingProviderError, DimensionMismatchError)):
            raise
        logger.error(f"Sentence-transformers embedding error: {e}")
        raise EmbeddingProviderError(
            f"Sentence-transformers error: {str(e)}"
        ) from e


def _embed_local(
    texts: list[str],
    *,
    embedding_model: EmbeddingModel,
) -> list[list[float]]:
    """
    Embed texts using a local embedding service (future implementation).

    This could call a FastAPI service running locally or on a GPU server.

    Args:
        texts: List of text strings
        embedding_model: EmbeddingModel instance

    Returns:
        List of embedding vectors

    Raises:
        EmbeddingProviderError: Not yet implemented
    """
    raise EmbeddingProviderError(
        "Local embedding provider not yet implemented. "
        "Use 'openai' or 'sentence-transformers' provider for now."
    )


def get_embedding_dimensions(model_name: str, provider: str = "openai") -> int:
    """
    Get the expected embedding dimensions for a model.

    Useful for creating EmbeddingModel records.

    Args:
        model_name: Name of the embedding model
        provider: Provider name (openai, sentence-transformers, etc.)

    Returns:
        Number of dimensions

    Raises:
        EmbeddingProviderError: If model is unknown
    """
    # OpenAI model dimensions (as of 2024)
    openai_dimensions = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    }

    if provider == "openai":
        if model_name in openai_dimensions:
            return openai_dimensions[model_name]
        else:
            raise EmbeddingProviderError(
                f"Unknown OpenAI model: {model_name}. "
                f"Known models: {list(openai_dimensions.keys())}"
            )

    elif provider == "sentence-transformers":
        # For sentence-transformers, we need to load the model to get dimensions
        try:
            from sentence_transformers import SentenceTransformer

            # Load on CPU to avoid MPS issues
            model = SentenceTransformer(model_name, device='cpu')
            return model.get_sentence_embedding_dimension()
        except ImportError:
            raise EmbeddingProviderError(
                "sentence-transformers not installed"
            )
        except Exception as e:
            raise EmbeddingProviderError(
                f"Could not load model {model_name}: {str(e)}"
            )

    else:
        raise EmbeddingProviderError(f"Unknown provider: {provider}")
