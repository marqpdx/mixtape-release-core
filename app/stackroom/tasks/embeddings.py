"""
Celery Tasks for Embeddings

Contract-compliant background tasks for embedding generation.

Tasks:
- embed_library: Backfill and enqueue embeddings for a library
- embed_chunk_embedding: Generate and store embedding for a single chunk
- embed_pending_batch: Process multiple chunk embeddings in one batch (NEW - High Performance)

Contract Rules:
- Tasks are idempotent (safe to retry)
- Failures are recorded, not hidden
- Status tracking in Django (PENDING → COMPLETE | FAILED)

Performance:
- Batch processing is 10-50x faster than one-at-a-time
- Use embed_pending_batch for new libraries
- Use embed_chunk_embedding for incremental updates
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from celery import shared_task
from django.db import transaction

from stackroom.models import (
    Library,
    EmbeddingModel,
    ChunkEmbedding,
    EmbeddingStatus,
)
from stackroom.services.embeddings import (
    get_or_create_embedding_model,
    backfill_chunk_embeddings,
    get_pending_embeddings,
)
from stackroom.services.qdrant_naming import get_collection_name_from_models
from stackroom.services.qdrant_client import (
    get_qdrant_client,
    build_payload_from_embedding,
)
from stackroom.services.embedding_provider import embed_texts

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def embed_library(
    self,
    library_id: str,
    model_name: str,
    model_version: str,
    provider: str = "openai",
) -> dict[str, int | str]:
    """
    Backfill and enqueue embeddings for an entire library.

    High-level orchestration task.

    Args:
        library_id: Library UUID (string)
        model_name: Embedding model name
        model_version: Embedding model version
        provider: Provider name

    Returns:
        Dict with stats: {created, existing, enqueued, collection}

    Raises:
        Exception: If library not found or critical error
    """
    try:
        # Get library
        library = Library.objects.get(id=library_id)
        logger.info(f"Starting embed_library for {library.name}")

        # Get or create embedding model
        embedding_model, created = get_or_create_embedding_model(
            name=model_name,
            version=model_version,
            provider=provider,
        )

        if created:
            logger.info(f"Created new EmbeddingModel: {embedding_model}")

        # Ensure Qdrant collection exists
        collection_name = get_collection_name_from_models(library, embedding_model)
        qdrant_client = get_qdrant_client()

        qdrant_client.ensure_collection(
            collection_name=collection_name,
            dimensions=embedding_model.dimensions,
        )

        # Backfill ChunkEmbedding rows
        stats = backfill_chunk_embeddings(library, embedding_model)

        # Enqueue pending embeddings using batch processing (HIGH PERFORMANCE)
        pending_count = ChunkEmbedding.objects.filter(
            library=library,
            embedding_model=embedding_model,
            status=EmbeddingStatus.PENDING,
        ).count()

        # Enqueue batch tasks (500 chunks per batch)
        batch_size = 500
        batches_enqueued = 0

        for offset in range(0, pending_count, batch_size):
            embed_pending_batch.delay(
                library_id=str(library.id),
                embedding_model_id=str(embedding_model.id),
                batch_size=batch_size,
            )
            batches_enqueued += 1

        logger.info(
            f"Embed library complete: {stats['created']} created, "
            f"{stats['existing']} existing, {pending_count} pending, "
            f"{batches_enqueued} batches enqueued"
        )

        return {
            "created": stats["created"],
            "existing": stats["existing"],
            "pending": pending_count,
            "batches_enqueued": batches_enqueued,
            "collection": collection_name,
        }

    except Library.DoesNotExist:
        logger.error(f"Library {library_id} not found")
        raise

    except Exception as e:
        logger.error(f"Error in embed_library: {e}")
        # Retry with exponential backoff
        raise self.retry(exc=e, countdown=2**self.request.retries)


@shared_task(bind=True, max_retries=5)
def embed_chunk_embedding(self, chunk_embedding_id: str) -> dict[str, str]:
    """
    Generate and store embedding for a single ChunkEmbedding.

    Idempotent: If already COMPLETE, returns early.

    Args:
        chunk_embedding_id: ChunkEmbedding UUID (string)

    Returns:
        Dict with result: {status, chunk_embedding_id, point_id}

    Raises:
        Exception: If embedding fails (will retry)
    """
    try:
        # Load ChunkEmbedding with related objects
        chunk_embedding = ChunkEmbedding.objects.select_related(
            "chunk",
            "chunk__artifact",
            "embedding_model",
            "library",
        ).get(id=chunk_embedding_id)

        # If already complete, return early (idempotency)
        if chunk_embedding.status == EmbeddingStatus.COMPLETE:
            logger.info(
                f"ChunkEmbedding {chunk_embedding_id} already COMPLETE, skipping"
            )
            return {
                "status": "already_complete",
                "chunk_embedding_id": str(chunk_embedding.id),
                "point_id": chunk_embedding.qdrant_point_id,
            }

        # Get text to embed
        text_to_embed = chunk_embedding.chunk.text

        # Generate embedding
        logger.info(f"Embedding chunk {chunk_embedding.chunk_id}")

        vectors = embed_texts(
            texts=[text_to_embed],
            embedding_model=chunk_embedding.embedding_model,
        )

        if not vectors or len(vectors) == 0:
            raise ValueError("No embedding returned from provider")

        vector = vectors[0]

        # Build payload (IDs only)
        payload = build_payload_from_embedding(chunk_embedding)

        # Upsert to Qdrant
        qdrant_client = get_qdrant_client()
        qdrant_client.upsert_point(
            collection_name=chunk_embedding.qdrant_collection,
            point_id=chunk_embedding.qdrant_point_id,
            vector=vector,
            payload=payload,
        )

        # Mark complete in Django
        chunk_embedding.mark_complete()
        chunk_embedding.save()

        logger.info(
            f"Successfully embedded chunk {chunk_embedding.chunk_id} "
            f"to {chunk_embedding.qdrant_collection}"
        )

        return {
            "status": "success",
            "chunk_embedding_id": str(chunk_embedding.id),
            "point_id": chunk_embedding.qdrant_point_id,
        }

    except ChunkEmbedding.DoesNotExist:
        logger.error(f"ChunkEmbedding {chunk_embedding_id} not found")
        # Don't retry for DoesNotExist
        return {
            "status": "not_found",
            "chunk_embedding_id": chunk_embedding_id,
        }

    except Exception as e:
        logger.error(f"Error embedding chunk {chunk_embedding_id}: {e}")

        # Mark as failed in Django
        try:
            chunk_embedding = ChunkEmbedding.objects.get(id=chunk_embedding_id)
            chunk_embedding.mark_failed(
                code=type(e).__name__,
                detail=str(e),
            )
            chunk_embedding.save()
        except Exception as save_error:
            logger.error(f"Could not mark embedding as failed: {save_error}")

        # Retry with exponential backoff
        raise self.retry(exc=e, countdown=2**self.request.retries)


@shared_task(bind=True, max_retries=3)
def embed_pending_batch(
    self,
    library_id: str,
    embedding_model_id: str,
    batch_size: int = 500,
) -> dict[str, int]:
    """
    Process multiple chunk embeddings in a single batch (HIGH PERFORMANCE).

    This task generates embeddings for multiple chunks in one API call,
    which is 10-50x faster than processing one-at-a-time.

    Batch Sizes:
    - OpenAI: Up to 2048 texts per call (uses batch_size parameter)
    - Sentence-transformers: Up to 512 texts per call (configurable)

    Args:
        library_id: Library UUID (required for filtering)
        embedding_model_id: EmbeddingModel UUID (required)
        batch_size: Number of chunks to process in this batch (default: 500)

    Returns:
        Dict with stats: {success, failed, skipped}

    Raises:
        Exception: If critical error (will retry)
    """
    try:
        # Load models
        library = Library.objects.get(id=library_id)
        embedding_model = EmbeddingModel.objects.get(id=embedding_model_id)

        logger.info(
            f"Starting batch embed for {library.name} with {embedding_model.name}, "
            f"batch_size={batch_size}"
        )

        # Get pending embeddings
        pending = get_pending_embeddings(
            library=library,
            embedding_model=embedding_model,
            limit=batch_size,
        )

        if not pending:
            logger.info("No pending embeddings found")
            return {"success": 0, "failed": 0, "skipped": 0}

        # Prepare batch data
        texts_to_embed = []
        chunk_embeddings_to_process = []

        for chunk_embedding in pending:
            # Skip if already complete (idempotency)
            if chunk_embedding.status == EmbeddingStatus.COMPLETE:
                continue

            texts_to_embed.append(chunk_embedding.chunk.text)
            chunk_embeddings_to_process.append(chunk_embedding)

        if not texts_to_embed:
            logger.info("All embeddings already complete")
            return {"success": 0, "failed": 0, "skipped": len(pending)}

        logger.info(f"Processing {len(texts_to_embed)} pending embeddings")

        # Generate embeddings for entire batch
        vectors = embed_texts(
            texts=texts_to_embed,
            embedding_model=embedding_model,
        )

        if len(vectors) != len(texts_to_embed):
            raise ValueError(
                f"Mismatch: got {len(vectors)} vectors for {len(texts_to_embed)} texts"
            )

        # Upsert to Qdrant and update Django
        qdrant_client = get_qdrant_client()
        success_count = 0
        failed_count = 0

        for i, (chunk_embedding, vector) in enumerate(
            zip(chunk_embeddings_to_process, vectors)
        ):
            try:
                # Build payload
                payload = build_payload_from_embedding(chunk_embedding)

                # Upsert to Qdrant
                qdrant_client.upsert_point(
                    collection_name=chunk_embedding.qdrant_collection,
                    point_id=chunk_embedding.qdrant_point_id,
                    vector=vector,
                    payload=payload,
                )

                # Mark complete
                chunk_embedding.mark_complete()
                chunk_embedding.save()

                success_count += 1

            except Exception as e:
                logger.error(
                    f"Failed to upsert chunk_embedding {chunk_embedding.id}: {e}"
                )

                # Mark as failed
                try:
                    chunk_embedding.mark_failed(
                        code=type(e).__name__,
                        detail=str(e),
                    )
                    chunk_embedding.save()
                except Exception as save_error:
                    logger.error(f"Could not mark as failed: {save_error}")

                failed_count += 1

        logger.info(
            f"Batch complete: {success_count} success, {failed_count} failed, "
            f"{len(pending) - len(chunk_embeddings_to_process)} skipped"
        )

        return {
            "success": success_count,
            "failed": failed_count,
            "skipped": len(pending) - len(chunk_embeddings_to_process),
        }

    except (Library.DoesNotExist, EmbeddingModel.DoesNotExist) as e:
        logger.error(f"Model not found: {e}")
        raise  # Don't retry for DoesNotExist

    except Exception as e:
        logger.error(f"Error in embed_pending_batch: {e}")
        # Retry with exponential backoff
        raise self.retry(exc=e, countdown=2**self.request.retries)
