# assets/tasks/cleanup.py

import logging
from celery import shared_task
from django.core.files.storage import default_storage
from celery.exceptions import MaxRetriesExceededError

from mixtape.storage_backends import PublicMediaStorage


logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    name="assets.tasks.delete_image_async",
)
def delete_image_async(self, s3_key):
    """
    Async task to delete an image from storage.

    Used for:
    - Deleting old images after commit (Save button)
    - Deleting pending images after rollback (Cancel button)

    Checks both PublicMediaStorage and the default (signed) storage --
    SponsorImageUploadView now writes public/profile/background/avatar
    images through PublicMediaStorage, but a key passed here as "old_key"
    may predate that change and still live under default_storage. See
    puddlejump/features/image-handling/image-handling-build-plan.md.

    Args:
        s3_key: S3 key/path of the image to delete

    Returns:
        dict with status and key
    """
    if not s3_key:
        logger.warning("[delete_image] No key provided, skipping")
        return {"status": "skipped", "reason": "no_key"}

    try:
        deleted_from = []

        if PublicMediaStorage().exists(s3_key):
            PublicMediaStorage().delete(s3_key)
            deleted_from.append("public")

        if default_storage.exists(s3_key):
            default_storage.delete(s3_key)
            deleted_from.append("default")

        if deleted_from:
            logger.info("[delete_image] Deleted image: %s (from: %s)", s3_key, ", ".join(deleted_from))
            return {"status": "deleted", "key": s3_key, "from": deleted_from}
        else:
            logger.warning("[delete_image] Image not found (already deleted?): %s", s3_key)
            return {"status": "not_found", "key": s3_key}

    except Exception as e:
        logger.error("[delete_image] Failed to delete %s: %s", s3_key, e, exc_info=True)

        try:
            # Retry with exponential backoff: 10s, 20s, 40s
            delay = 2 ** self.request.retries * 10
            logger.info("[delete_image] Retrying in %ds (retry #%s)", delay, self.request.retries + 1)
            raise self.retry(exc=e, countdown=delay)
        except MaxRetriesExceededError:
            logger.error("[delete_image] Max retries exceeded for %s", s3_key)
            return {"status": "failed", "key": s3_key, "error": str(e)}
