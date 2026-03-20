# stackroom/tasks/milldraft.py
#
# Celery task: promote a processed Stackroom Artifact into the MillDraft Review Queue.

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from celery import shared_task

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def create_milldraft_from_artifact_task(
    self,
    artifact_id: str,
    content_profile: str | None = None,
) -> dict:
    """
    Create a MillDraft candidate from a fully-processed Stackroom Artifact.

    Called after process_artifact (chunking + embedding) completes.
    Idempotent — safe to retry.

    Args:
        artifact_id:     UUID string of the Stackroom Artifact.
        content_profile: Optional override for content profile.

    Returns:
        Dict with draft_id + suggestion_id, or {"skipped": True} if already exists.
    """
    from stackroom.services.milldraft_connector import create_milldraft_from_artifact

    try:
        result = create_milldraft_from_artifact(
            artifact_id=artifact_id,
            content_profile=content_profile,
        )
        if result is None:
            return {"skipped": True, "artifact_id": artifact_id}

        logger.info(
            "create_milldraft_from_artifact_task: done — draft=%s suggestion=%s",
            result["draft_id"],
            result["suggestion_id"],
        )
        return {**result, "artifact_id": artifact_id}

    except Exception as exc:
        logger.error(
            "create_milldraft_from_artifact_task: failed for artifact %s: %s",
            artifact_id,
            exc,
        )
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)
