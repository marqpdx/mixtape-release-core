# stackroom/tasks/metadata.py

"""
Celery Tasks for Artifact Metadata Extraction

Extracts interior_summary and keywords from Artifacts for Simple Search.
Runs after text extraction, before/parallel to chunking and embedding.

Tasks:
- extract_artifact_metadata_task: Process a single Artifact
- backfill_artifact_metadata: Batch process existing Artifacts

Contract Rules:
- Tasks are idempotent (safe to retry)
- Failures are logged, not hidden
- No external API calls (pure CPU processing)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from celery import shared_task
from django.db import transaction

from stackroom.models import Artifact
from stackroom.services.metadata_extraction import extract_artifact_metadata

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def extract_artifact_metadata_task(
    self,
    artifact_id: str,
    summary_method: str = 'simple',
    keywords_method: str = 'tfidf',
) -> dict[str, str | int]:
    """
    Extract interior_summary and keywords for a single Artifact.

    Idempotent: If already extracted (metadata_version exists), skips or re-extracts.

    Args:
        artifact_id: Artifact UUID (string)
        summary_method: 'simple' | 'inkwell'
        keywords_method: 'tfidf' | 'rake'

    Returns:
        Dict with result: {status, artifact_id, summary_length, keyword_count}

    Raises:
        Exception: If extraction fails (will retry)
    """
    try:
        # Load Artifact
        artifact = Artifact.objects.select_related('source_file').get(id=artifact_id)

        # Check if already extracted (idempotency)
        if artifact.metadata_version:
            logger.info(
                f"Artifact {artifact_id} already has metadata (version={artifact.metadata_version}), skipping"
            )
            return {
                'status': 'already_extracted',
                'artifact_id': str(artifact.id),
                'summary_length': len(artifact.interior_summary),
                'keyword_count': len(artifact.keywords),
            }

        # Check if text exists
        if not artifact.text or len(artifact.text.strip()) < 50:
            logger.warning(f"Artifact {artifact_id} has insufficient text (<50 chars), skipping")
            return {
                'status': 'insufficient_text',
                'artifact_id': str(artifact.id),
                'summary_length': 0,
                'keyword_count': 0,
            }

        # Extract metadata
        logger.info(f"Extracting metadata for Artifact {artifact_id}")

        metadata = extract_artifact_metadata(
            artifact=artifact,
            summary_method=summary_method,
            keywords_method=keywords_method,
            metadata_version=f'1.0-{summary_method}',
        )

        # Save to database
        with transaction.atomic():
            artifact.interior_summary = metadata['interior_summary']
            artifact.keywords = metadata['keywords']
            artifact.metadata_version = metadata['metadata_version']
            artifact.save(update_fields=['interior_summary', 'keywords', 'metadata_version'])

        logger.info(
            f"Successfully extracted metadata for Artifact {artifact_id}: "
            f"summary={len(metadata['interior_summary'])} chars, "
            f"keywords={len(metadata['keywords'])} terms"
        )

        return {
            'status': 'success',
            'artifact_id': str(artifact.id),
            'summary_length': len(metadata['interior_summary']),
            'keyword_count': len(metadata['keywords']),
        }

    except Artifact.DoesNotExist:
        logger.error(f"Artifact {artifact_id} not found")
        return {
            'status': 'not_found',
            'artifact_id': artifact_id,
            'summary_length': 0,
            'keyword_count': 0,
        }

    except Exception as e:
        logger.error(f"Error extracting metadata for Artifact {artifact_id}: {e}")

        # Retry with exponential backoff
        raise self.retry(exc=e, countdown=2**self.request.retries)


@shared_task(bind=True, max_retries=2)
def backfill_artifact_metadata(
    self,
    library_id: str | None = None,
    batch_size: int = 100,
    summary_method: str = 'simple',
) -> dict[str, int]:
    """
    Backfill metadata for existing Artifacts (batch operation).

    Useful for:
    - Initial migration (extract metadata for all existing Artifacts)
    - Re-extraction with new logic (e.g., switching to Inkwell)

    Args:
        library_id: Optional Library UUID to filter by (None = all libraries)
        batch_size: Number of Artifacts to process per batch
        summary_method: 'simple' | 'inkwell'

    Returns:
        Dict with stats: {enqueued, skipped, no_text}

    Raises:
        Exception: If critical error (will retry)
    """
    try:
        # Build query
        artifacts_query = Artifact.objects.filter(
            artifact_type='extracted_text',  # Only process text artifacts
            metadata_version='',  # Only process artifacts without metadata
        )

        if library_id:
            artifacts_query = artifacts_query.filter(source_file__library_id=library_id)

        # Count artifacts
        total_artifacts = artifacts_query.count()

        if total_artifacts == 0:
            logger.info("No artifacts need metadata extraction")
            return {'enqueued': 0, 'skipped': 0, 'no_text': 0}

        logger.info(
            f"Backfilling metadata for {total_artifacts} artifacts "
            f"(library_id={library_id}, method={summary_method})"
        )

        # Enqueue tasks
        enqueued_count = 0
        skipped_count = 0
        no_text_count = 0

        for artifact in artifacts_query[:batch_size]:
            # Skip if no text
            if not artifact.text or len(artifact.text.strip()) < 50:
                no_text_count += 1
                continue

            # Enqueue extraction task
            extract_artifact_metadata_task.delay(
                artifact_id=str(artifact.id),
                summary_method=summary_method,
            )
            enqueued_count += 1

        logger.info(
            f"Backfill complete: {enqueued_count} enqueued, "
            f"{skipped_count} skipped, {no_text_count} no text"
        )

        return {
            'enqueued': enqueued_count,
            'skipped': skipped_count,
            'no_text': no_text_count,
        }

    except Exception as e:
        logger.error(f"Error in backfill_artifact_metadata: {e}")
        raise self.retry(exc=e, countdown=2**self.request.retries)
