"""
Celery tasks for retrieval and query logging.
"""
from __future__ import annotations

import hashlib
from celery import shared_task


@shared_task(bind=True, max_retries=3)
def log_query_async(
    self,
    library_id: str,
    user_id: int | None,
    query_text: str,
    embedding_model_id: str,
    limit: int,
    score_threshold: float | None,
    artifact_types: list[str] | None,
    source_file_ids: list[str] | None,
    result_count: int,
    timing: dict,
    error_code: str | None = None,
    error_detail: str | None = None,
):
    """
    Asynchronously log a retrieval query for observability.

    This task runs in the background and does not block the response.
    """
    from stackroom.models import QueryLog

    try:
        # Hash the query text for privacy
        query_hash = hashlib.sha256(query_text.encode()).hexdigest()

        # Create the query log
        QueryLog.objects.create(
            library_id=library_id,
            user_id=user_id,
            query_hash=query_hash,
            query_length=len(query_text),
            embedding_model_id=embedding_model_id,
            limit=limit,
            score_threshold=score_threshold,
            artifact_types=artifact_types,
            source_file_ids=source_file_ids,
            result_count=result_count,
            embed_ms=timing.get("embed_ms"),
            qdrant_ms=timing.get("qdrant_ms"),
            resolve_ms=timing.get("resolve_ms"),
            total_ms=timing.get("total_ms"),
            error_code=error_code,
            error_detail=error_detail,
        )

        return {"status": "logged", "query_hash": query_hash}

    except Exception as e:
        # Retry on failure
        raise self.retry(exc=e, countdown=60)
