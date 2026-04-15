from __future__ import annotations

import logging

from celery import shared_task
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from stackroom.models import StackroomSyncState

logger = logging.getLogger(__name__)


def _load_target(content_type_id: int, object_id: str):
    content_type = ContentType.objects.get_for_id(content_type_id)
    model_class = content_type.model_class()
    if model_class is None:
        raise LookupError(f"ContentType {content_type_id} has no model class")
    return model_class.objects.get(pk=object_id)


@shared_task(bind=True, max_retries=3, default_retry_delay=15)
def ingest_object_task(
    self,
    *,
    content_type_id: int,
    object_id: str,
    adapter_name: str,
    reason: str,
    force: bool = False,
):
    sync_state = StackroomSyncState.objects.filter(
        content_type_id=content_type_id,
        object_id=object_id,
        adapter_name=adapter_name,
    ).first()

    if sync_state:
        sync_state.status = StackroomSyncState.STATUS_PENDING
        sync_state.last_error = ""
        sync_state.metadata = {**(sync_state.metadata or {}), "queued_reason": reason, "last_queued_at": timezone.now().isoformat()}
        sync_state.save(update_fields=["status", "last_error", "metadata", "updated_at"])

    try:
        obj = _load_target(content_type_id, object_id)
    except ObjectDoesNotExist:
        logger.info("Stackroom ingest target disappeared before task ran: %s:%s", content_type_id, object_id)
        if sync_state:
            sync_state.status = StackroomSyncState.STATUS_DEACTIVATED
            sync_state.last_error = ""
            sync_state.save(update_fields=["status", "last_error", "updated_at"])
        return {"status": "missing", "content_type_id": content_type_id, "object_id": object_id}

    try:
        from stackroom.integration.service import ingest_object
        sync_state = ingest_object(obj, reason=reason, force=force)
        return {
            "status": sync_state.status,
            "object_id": object_id,
            "adapter_name": adapter_name,
        }
    except Exception as exc:
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


@shared_task(bind=True, max_retries=3, default_retry_delay=15)
def deactivate_object_task(
    self,
    *,
    content_type_id: int,
    object_id: str,
    adapter_name: str,
    reason: str,
):
    sync_state = StackroomSyncState.objects.filter(
        content_type_id=content_type_id,
        object_id=object_id,
        adapter_name=adapter_name,
    ).first()

    if sync_state:
        sync_state.status = StackroomSyncState.STATUS_PENDING
        sync_state.last_error = ""
        sync_state.metadata = {**(sync_state.metadata or {}), "queued_reason": reason, "last_queued_at": timezone.now().isoformat()}
        sync_state.save(update_fields=["status", "last_error", "metadata", "updated_at"])

    try:
        obj = _load_target(content_type_id, object_id)
    except ObjectDoesNotExist:
        logger.info("Stackroom deactivate target disappeared before task ran: %s:%s", content_type_id, object_id)
        if sync_state:
            sync_state.status = StackroomSyncState.STATUS_DEACTIVATED
            sync_state.last_error = ""
            sync_state.save(update_fields=["status", "last_error", "updated_at"])
        return {"status": "missing", "content_type_id": content_type_id, "object_id": object_id}

    try:
        from stackroom.integration.service import deactivate_object
        sync_state = deactivate_object(obj, reason=reason)
        if sync_state is None:
            return {"status": "noop", "object_id": object_id, "adapter_name": adapter_name}
        return {
            "status": sync_state.status,
            "object_id": object_id,
            "adapter_name": adapter_name,
        }
    except Exception as exc:
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)
