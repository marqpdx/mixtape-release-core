"""
Celery Tasks for Artifact Processing

Full pipeline: Artifact → Chunks → Embeddings

Tasks:
- process_artifact: Chunk artifact and trigger embedding generation
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from celery import shared_task
from django.db import transaction

from stackroom.models import Artifact, IngestionRun
from stackroom.services.chunking import chunk_artifact
from stackroom.tasks.embeddings import embed_library

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def process_artifact(
    self,
    artifact_id: str,
    model_name: str = "all-mpnet-base-v2",
    model_version: str = "1",
    provider: str = "sentence-transformers",
) -> dict[str, int | str]:
    """
    Process an artifact: chunk it and generate embeddings.

    This is the main post-upload pipeline task.

    Args:
        artifact_id: Artifact UUID (string)
        model_name: Embedding model name
        model_version: Embedding model version
        provider: Provider name

    Returns:
        Dict with stats: {artifact_id, chunks_created, embedding_task_id}

    Raises:
        Exception: If artifact not found or critical error
    """
    try:
        # Get artifact
        try:
            artifact = Artifact.objects.get(id=artifact_id)
        except Artifact.DoesNotExist:
            logger.error(f"Artifact {artifact_id} not found")
            raise

        logger.info(f"Processing artifact {artifact_id}: {artifact.artifact_type}")

        # Step 1: Chunk the artifact
        with transaction.atomic():
            chunks = chunk_artifact(
                artifact=artifact,
                strategy="paragraph",
                target_chunk_size=400,
                max_chunk_size=600,
            )

        chunks_created = len(chunks)
        logger.info(f"Created {chunks_created} chunks for artifact {artifact_id}")

        # Step 2: Trigger embedding generation for the library
        # This will process all pending chunks (including the ones we just created)
        library_id = str(artifact.source_file.library.id)

        embedding_task = embed_library.delay(
            library_id=library_id,
            model_name=model_name,
            model_version=model_version,
            provider=provider,
        )

        logger.info(
            f"Triggered embedding generation for library {library_id} "
            f"(task: {embedding_task.id})"
        )

        # Step 3: Update ingestion run status
        try:
            from django.utils import timezone
            ingestion_run = IngestionRun.objects.filter(
                source_file__artifacts__id=artifact_id
            ).first()
            if ingestion_run:
                ingestion_run.status = "success"
                ingestion_run.completed_at = timezone.now()
                ingestion_run.save()
                logger.info(f"Marked ingestion run {ingestion_run.id} as complete")
        except Exception as e:
            logger.warning(f"Failed to update ingestion run status: {str(e)}")

        return {
            "artifact_id": artifact_id,
            "chunks_created": chunks_created,
            "embedding_task_id": str(embedding_task.id),
            "status": "success",
        }

    except Exception as e:
        logger.error(f"Failed to process artifact {artifact_id}: {str(e)}")
        # Update ingestion run status if available
        try:
            ingestion_run = IngestionRun.objects.filter(
                source_file__artifacts__id=artifact_id
            ).first()
            if ingestion_run:
                ingestion_run.status = "failed"
                ingestion_run.save()
        except Exception:
            pass  # Don't fail the task if status update fails

        # Retry with exponential backoff
        raise self.retry(exc=e, countdown=2 ** self.request.retries)
