# commons/tasks.py
#
# Celery tasks for the Commons extraction pipeline.

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def extract_commons_item_task(self, item_id: str):
    """
    Fetch and extract structured data for a CommonsItem from its source_url.

    Triggered automatically after capture_item() creates a CommonsItem.
    Populates extracted fields on the item so the curator sees pre-filled data
    rather than an empty form in the Curation Station.

    Fails gracefully: if Inkwell is unavailable or extraction fails, the item
    stays in the queue with just the source_url. The curator fills it in manually.
    """
    from inkwell.client import extract_commons, InkwellUnavailableError
    from commons.models import CommonsItem

    try:
        item = CommonsItem.objects.get(pk=item_id, deleted_at__isnull=True)
    except CommonsItem.DoesNotExist:
        logger.warning("[extract_commons_task] Item %s not found, skipping", item_id)
        return

    if not item.source_url:
        logger.info("[extract_commons_task] Item %s has no source_url, skipping", item_id)
        return

    logger.info(
        "[extract_commons_task] Extracting %s for item %s",
        item.source_url,
        item_id,
    )

    try:
        data = extract_commons(item.source_url)
    except InkwellUnavailableError as e:
        logger.warning(
            "[extract_commons_task] Inkwell unavailable for item %s: %s",
            item_id, e,
        )
        # Retry up to max_retries times; after that, leave item as-is
        try:
            raise self.retry(exc=e)
        except self.MaxRetriesExceededError:
            logger.error(
                "[extract_commons_task] Max retries exceeded for item %s — "
                "curator will fill manually",
                item_id,
            )
        return
    except Exception as e:
        logger.error(
            "[extract_commons_task] Unexpected error for item %s: %s",
            item_id, e, exc_info=True,
        )
        return

    # Store the full raw extraction result for curator reference
    item.extracted_data = data

    # Apply extracted fields only where the item field is still blank.
    # We never overwrite data that was explicitly set by the submitting member.
    changed = False

    def _apply(field: str, value: str):
        nonlocal changed
        if value and not getattr(item, field, ""):
            setattr(item, field, value)
            changed = True

    _apply("title", data.get("name", ""))
    _apply("summary", data.get("description", ""))
    _apply("location_name", data.get("location", ""))
    _apply("founder", data.get("founder", ""))
    _apply("website", data.get("website", ""))
    _apply("instagram", data.get("instagram", ""))
    _apply("youtube", data.get("youtube", ""))
    _apply("contact_email", data.get("contact_email", ""))

    # item_type: only apply if extracted a valid non-empty type
    extracted_type = data.get("item_type", "")
    if extracted_type and not item.item_type:
        item.item_type = extracted_type
        changed = True

    # Merge additional_data — always store, even if item already has some
    extracted_additional = data.get("additional_data", {})
    if extracted_additional:
        existing = item.additional_data or {}
        item.additional_data = {**extracted_additional, **existing}
        changed = True

    item.save()

    logger.info(
        "[extract_commons_task] Extraction complete for item %s "
        "(method=%s, fields_changed=%s)",
        item_id,
        data.get("extraction_method", "?"),
        changed,
    )
