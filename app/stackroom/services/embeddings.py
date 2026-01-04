"""
Embedding Service Layer

Orchestrates the embedding pipeline:
- EmbeddingModel resolution
- ChunkEmbedding backfill
- Queue orchestration

Contract Rules:
- Backfills are retry-safe (idempotent)
- No duplicate ChunkEmbedding rows can be created
- Only PENDING rows are enqueued
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Q

from stackroom.models import (
    Library,
    SourceFile,
    Artifact,
    Chunk,
    EmbeddingModel,
    ChunkEmbedding,
    EmbeddingStatus,
)
from stackroom.services.qdrant_naming import get_collection_name_from_models
from stackroom.services.qdrant_client import get_qdrant_client
from stackroom.services.embedding_provider import get_embedding_dimensions

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)


class EmbeddingServiceError(Exception):
    """Base exception for embedding service errors"""

    pass


def get_or_create_embedding_model(
    name: str,
    version: str,
    provider: str = "openai",
    dimensions: int | None = None,
    normalize: bool = False,
) -> tuple[EmbeddingModel, bool]:
    """
    Get or create an EmbeddingModel by (name, version).

    If dimensions is not provided, attempts to infer from provider.

    Args:
        name: Model name (e.g., "text-embedding-3-small")
        version: Model version (e.g., "1")
        provider: Provider name (openai, sentence-transformers, local)
        dimensions: Vector dimensions (inferred if not provided)
        normalize: Whether to normalize vectors

    Returns:
        Tuple of (EmbeddingModel, created: bool)

    Raises:
        EmbeddingServiceError: If dimensions cannot be inferred or mismatch
    """
    # Try to get existing model
    try:
        model = EmbeddingModel.objects.get(name=name, version=version)

        # Validate dimensions match if provided
        if dimensions is not None and model.dimensions != dimensions:
            raise EmbeddingServiceError(
                f"EmbeddingModel {name}@{version} exists with {model.dimensions} dimensions, "
                f"expected {dimensions}"
            )

        logger.info(f"Found existing EmbeddingModel: {model}")
        return model, False

    except EmbeddingModel.DoesNotExist:
        # Need to create new model
        if dimensions is None:
            # Infer dimensions from provider
            try:
                dimensions = get_embedding_dimensions(name, provider)
                logger.info(f"Inferred {dimensions} dimensions for {name} ({provider})")
            except Exception as e:
                raise EmbeddingServiceError(
                    f"Could not infer dimensions for {name}: {str(e)}"
                ) from e

        # Create model
        model = EmbeddingModel.objects.create(
            name=name,
            version=version,
            provider=provider,
            dimensions=dimensions,
            normalize=normalize,
        )

        logger.info(f"Created EmbeddingModel: {model}")
        return model, True


def backfill_chunk_embeddings(
    library: Library,
    embedding_model: EmbeddingModel,
) -> dict[str, int]:
    """
    Backfill missing ChunkEmbedding rows for a library.

    Idempotent: Safe to call multiple times.

    Traversal: Library → SourceFile → Artifact → Chunk

    Args:
        library: Library to backfill
        embedding_model: EmbeddingModel to use

    Returns:
        Dict with counts: {"created": N, "existing": M}
    """
    collection_name = get_collection_name_from_models(library, embedding_model)

    created_count = 0
    existing_count = 0

    # Traverse hierarchy
    for source_file in library.source_files.all():
        for artifact in source_file.artifacts.all():
            for chunk in artifact.chunks.all():
                # Compute text hash
                text_hash = hashlib.sha256(chunk.text.encode()).hexdigest()

                # Check if embedding already exists
                existing = ChunkEmbedding.objects.filter(
                    chunk=chunk,
                    embedding_model=embedding_model,
                    embedded_text_hash=text_hash,
                ).exists()

                if existing:
                    existing_count += 1
                    continue

                # Create new ChunkEmbedding
                ChunkEmbedding.objects.create(
                    chunk=chunk,
                    embedding_model=embedding_model,
                    library=library,
                    embedded_text_hash=text_hash,
                    qdrant_collection=collection_name,
                    qdrant_point_id=str(chunk.id),
                    status=EmbeddingStatus.PENDING,
                )

                created_count += 1

    logger.info(
        f"Backfill complete for {library.name}: "
        f"{created_count} created, {existing_count} existing"
    )

    return {"created": created_count, "existing": existing_count}


def backfill_library_embeddings(
    library_id: UUID | str,
    model_name: str,
    model_version: str,
    provider: str = "openai",
) -> dict[str, int | str]:
    """
    Backfill embeddings for an entire library.

    High-level orchestration function.

    Args:
        library_id: Library UUID
        model_name: Embedding model name
        model_version: Embedding model version
        provider: Provider name

    Returns:
        Dict with results: {"created": N, "existing": M, "collection": "..."}

    Raises:
        EmbeddingServiceError: If library not found or other errors
    """
    try:
        library = Library.objects.get(id=library_id)
    except Library.DoesNotExist:
        raise EmbeddingServiceError(f"Library {library_id} not found")

    # Get or create embedding model
    embedding_model, _ = get_or_create_embedding_model(
        name=model_name,
        version=model_version,
        provider=provider,
    )

    # Ensure Qdrant collection exists
    collection_name = get_collection_name_from_models(library, embedding_model)
    qdrant_client = get_qdrant_client()

    qdrant_client.ensure_collection(
        collection_name=collection_name,
        dimensions=embedding_model.dimensions,
    )

    # Backfill ChunkEmbedding rows
    stats = backfill_chunk_embeddings(library, embedding_model)
    stats["collection"] = collection_name

    return stats


def get_pending_embeddings(
    library: Library | None = None,
    embedding_model: EmbeddingModel | None = None,
    limit: int | None = None,
) -> list[ChunkEmbedding]:
    """
    Get pending ChunkEmbedding rows ready for processing.

    Args:
        library: Filter by library (optional)
        embedding_model: Filter by model (optional)
        limit: Maximum number to return (optional)

    Returns:
        List of ChunkEmbedding instances with status=PENDING
    """
    queryset = ChunkEmbedding.objects.filter(status=EmbeddingStatus.PENDING)

    if library:
        queryset = queryset.filter(library=library)

    if embedding_model:
        queryset = queryset.filter(embedding_model=embedding_model)

    # Optimize query with select_related
    queryset = queryset.select_related("chunk", "embedding_model", "library")

    if limit:
        queryset = queryset[:limit]

    return list(queryset)


def get_stale_embeddings(
    library: Library | None = None,
    embedding_model: EmbeddingModel | None = None,
) -> list[ChunkEmbedding]:
    """
    Find embeddings where chunk.text has changed (stale).

    Detects drift: embedded_text_hash != hash(chunk.text)

    Args:
        library: Filter by library (optional)
        embedding_model: Filter by model (optional)

    Returns:
        List of stale ChunkEmbedding instances
    """
    queryset = ChunkEmbedding.objects.filter(status=EmbeddingStatus.COMPLETE)

    if library:
        queryset = queryset.filter(library=library)

    if embedding_model:
        queryset = queryset.filter(embedding_model=embedding_model)

    queryset = queryset.select_related("chunk", "embedding_model", "library")

    # Check each embedding for staleness
    stale = []
    for embedding in queryset:
        current_hash = hashlib.sha256(embedding.chunk.text.encode()).hexdigest()
        if embedding.embedded_text_hash != current_hash:
            stale.append(embedding)

    logger.info(f"Found {len(stale)} stale embeddings")
    return stale


def mark_stale_embeddings_pending(
    library: Library | None = None,
    embedding_model: EmbeddingModel | None = None,
) -> int:
    """
    Mark stale embeddings as PENDING for re-embedding.

    Args:
        library: Filter by library (optional)
        embedding_model: Filter by model (optional)

    Returns:
        Number of embeddings marked as PENDING
    """
    stale = get_stale_embeddings(library, embedding_model)

    count = 0
    for embedding in stale:
        # Update text hash and status
        new_hash = hashlib.sha256(embedding.chunk.text.encode()).hexdigest()
        embedding.embedded_text_hash = new_hash
        embedding.status = EmbeddingStatus.PENDING
        embedding.save()
        count += 1

    logger.info(f"Marked {count} stale embeddings as PENDING")
    return count


def get_embedding_stats(
    library: Library | None = None,
    embedding_model: EmbeddingModel | None = None,
) -> dict[str, int]:
    """
    Get statistics about embeddings.

    Args:
        library: Filter by library (optional)
        embedding_model: Filter by model (optional)

    Returns:
        Dict with counts by status
    """
    queryset = ChunkEmbedding.objects.all()

    if library:
        queryset = queryset.filter(library=library)

    if embedding_model:
        queryset = queryset.filter(embedding_model=embedding_model)

    return {
        "total": queryset.count(),
        "pending": queryset.filter(status=EmbeddingStatus.PENDING).count(),
        "complete": queryset.filter(status=EmbeddingStatus.COMPLETE).count(),
        "failed": queryset.filter(status=EmbeddingStatus.FAILED).count(),
    }


def delete_library_embeddings(
    library: Library,
    embedding_model: EmbeddingModel | None = None,
    delete_from_qdrant: bool = True,
) -> int:
    """
    Delete embeddings for a library.

    WARNING: Destructive operation.

    Args:
        library: Library to delete embeddings for
        embedding_model: Filter by model (optional, deletes all if None)
        delete_from_qdrant: Also delete from Qdrant (default: True)

    Returns:
        Number of ChunkEmbedding rows deleted
    """
    queryset = ChunkEmbedding.objects.filter(library=library)

    if embedding_model:
        queryset = queryset.filter(embedding_model=embedding_model)

    # Get collection names before deleting
    if delete_from_qdrant:
        collections = set(
            queryset.values_list("qdrant_collection", flat=True).distinct()
        )

        qdrant_client = get_qdrant_client()
        for collection_name in collections:
            if qdrant_client.collection_exists(collection_name):
                qdrant_client.delete_collection(collection_name)
                logger.info(f"Deleted Qdrant collection: {collection_name}")

    # Delete ChunkEmbedding rows
    count, _ = queryset.delete()

    logger.info(f"Deleted {count} ChunkEmbedding rows for library {library.name}")
    return count
