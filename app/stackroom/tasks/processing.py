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


@shared_task
def process_pending_uploads() -> dict[str, int]:
    """
    Periodic task to process SourceFiles without IngestionRuns.

    This task:
    1. Finds SourceFiles that haven't been ingested yet
    2. Reads their content from storage
    3. Extracts text and creates Artifacts
    4. Queues them for chunking and embedding

    Designed for Collection uploads where ingestion is deferred.
    Runs periodically (every 15 seconds) via Celery Beat.

    Returns:
        Dict with stats: {processed_count, failed_count, skipped_count}
    """
    from django.core.files.storage import default_storage
    from stackroom.models import SourceFile, IngestionReceipt

    logger.info("Starting process_pending_uploads task")

    # Find SourceFiles without IngestionRuns (unprocessed uploads)
    unprocessed_files = SourceFile.objects.filter(
        ingestion_runs__isnull=True
    ).order_by('created_at')[:10]  # Process up to 10 files per run

    if not unprocessed_files:
        logger.info("No pending uploads to process")
        return {"processed_count": 0, "failed_count": 0, "skipped_count": 0}

    logger.info(f"Found {len(unprocessed_files)} unprocessed files")

    processed_count = 0
    failed_count = 0
    skipped_count = 0

    for source_file in unprocessed_files:
        try:
            logger.info(f"Processing {source_file.filename} (ID: {source_file.id})")

            # Create IngestionRun
            ingestion_run = IngestionRun.objects.create(
                source_file=source_file,
                status="running",
            )

            # Read file from storage
            if not default_storage.exists(source_file.path):
                logger.error(f"File not found in storage: {source_file.path}")
                ingestion_run.status = "failed"
                ingestion_run.save()
                failed_count += 1
                continue

            # Read file content
            with default_storage.open(source_file.path, 'rb') as file_handle:
                file_content = file_handle.read()

            # Extract text from file
            try:
                extracted_text = _extract_text_from_bytes(
                    file_content,
                    source_file.filename,
                    source_file.content_type
                )
            except Exception as e:
                logger.error(f"Text extraction failed for {source_file.filename}: {str(e)}")
                extracted_text = f"[Text extraction failed: {str(e)}]"

            # Create Artifact with extracted text
            artifact = Artifact.objects.create(
                source_file=source_file,
                artifact_uid=f"extracted_text_{source_file.hash_sha256[:16]}",
                artifact_type="extracted_text",
                format="text/plain",
                text=extracted_text,
            )

            logger.info(f"Created artifact {artifact.id} with {len(extracted_text)} characters")

            # Create IngestionReceipt
            IngestionReceipt.objects.create(
                run=ingestion_run,
                status="success",
                payload={
                    "source_file_id": str(source_file.id),
                    "artifact_id": str(artifact.id),
                    "extracted_length": len(extracted_text),
                },
            )

            # Queue metadata extraction (interior_summary + keywords)
            # This runs in parallel to chunking/embedding and is fast (no external API)
            from stackroom.tasks.metadata import extract_artifact_metadata_task
            extract_artifact_metadata_task.delay(
                artifact_id=str(artifact.id),
                summary_method='simple',  # Can be switched to 'inkwell' later
            )

            # Queue chunking and embedding tasks
            process_artifact.delay(
                artifact_id=str(artifact.id),
                model_name="all-mpnet-base-v2",
                model_version="1",
                provider="sentence-transformers",
            )

            # Queue MillDraft candidate creation (surfaces artifact in Review Queue)
            from stackroom.tasks.milldraft import create_milldraft_from_artifact_task
            create_milldraft_from_artifact_task.delay(artifact_id=str(artifact.id))

            logger.info(f"Successfully queued processing for {source_file.filename}")
            processed_count += 1

        except Exception as e:
            logger.error(f"Failed to process {source_file.filename}: {str(e)}")
            failed_count += 1

    logger.info(
        f"process_pending_uploads complete: "
        f"processed={processed_count}, failed={failed_count}, skipped={skipped_count}"
    )

    return {
        "processed_count": processed_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
    }


def _extract_text_from_bytes(file_content: bytes, filename: str, content_type: str) -> str:
    """
    Extract text content from file bytes.

    Supports:
    - Plain text (.txt, .md, .json, .csv, .html)
    - PDF files (.pdf) - requires PyPDF2
    - Word documents (.docx) - requires python-docx

    Args:
        file_content: Raw file bytes
        filename: Original filename
        content_type: MIME content type

    Returns:
        Extracted text content
    """
    import io

    file_extension = filename.lower().split('.')[-1]

    # Plain text files
    if file_extension in ['txt', 'md', 'json', 'csv', 'html', 'xml', 'yaml', 'yml']:
        try:
            # Try UTF-8 first, fall back to latin-1
            try:
                return file_content.decode('utf-8')
            except UnicodeDecodeError:
                return file_content.decode('latin-1', errors='ignore')
        except Exception as e:
            logger.error(f"Failed to decode text file {filename}: {str(e)}")
            return f"[Failed to decode text: {str(e)}]"

    # PDF files
    if file_extension == 'pdf':
        try:
            import PyPDF2
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_content))
            text_parts = []
            for page in pdf_reader.pages:
                text_parts.append(page.extract_text())
            return '\n\n'.join(text_parts)
        except Exception as e:
            logger.error(f"Failed to extract PDF text from {filename}: {str(e)}")
            return f"[PDF extraction failed: {str(e)}]"

    # Word documents
    if file_extension in ['docx', 'doc']:
        try:
            import docx
            doc = docx.Document(io.BytesIO(file_content))
            text_parts = [paragraph.text for paragraph in doc.paragraphs]
            return '\n\n'.join(text_parts)
        except Exception as e:
            logger.error(f"Failed to extract Word doc text from {filename}: {str(e)}")
            return f"[Word doc extraction failed: {str(e)}]"

    # Unsupported file type
    logger.warning(f"Unsupported file type for text extraction: {filename} ({file_extension})")
    return f"[Unsupported file type: {file_extension}]"
