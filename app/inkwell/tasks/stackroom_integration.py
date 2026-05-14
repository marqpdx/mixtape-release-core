from __future__ import annotations

import logging

from celery import shared_task
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist

logger = logging.getLogger(__name__)


def _load_object(content_type_id: int, object_id: str):
    ct = ContentType.objects.get_for_id(content_type_id)
    model_class = ct.model_class()
    if model_class is None:
        raise LookupError(f"ContentType {content_type_id} has no model class")
    return model_class.objects.get(pk=object_id)


@shared_task(bind=True, max_retries=3, default_retry_delay=15)
def ingest_object_task(self, *, content_type_id: int, object_id: str, reason: str, force: bool = False):
    try:
        obj = _load_object(content_type_id, object_id)
    except ObjectDoesNotExist:
        logger.info("Stackroom ingest target gone before task ran: ct=%s id=%s", content_type_id, object_id)
        return {"status": "missing"}

    try:
        from inkwell.stackroom_integration_service import ingest_object
        sync_state = ingest_object(obj, reason=reason, force=force)
        return {"status": sync_state.status, "object_id": object_id}
    except Exception as exc:
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


@shared_task(bind=True, max_retries=3, default_retry_delay=15)
def deactivate_object_task(self, *, content_type_id: int, object_id: str, reason: str):
    try:
        obj = _load_object(content_type_id, object_id)
    except ObjectDoesNotExist:
        logger.info("Stackroom deactivate target gone before task ran: ct=%s id=%s", content_type_id, object_id)
        return {"status": "missing"}

    try:
        from inkwell.stackroom_integration_service import deactivate_object
        sync_state = deactivate_object(obj, reason=reason)
        if sync_state is None:
            return {"status": "noop", "object_id": object_id}
        return {"status": sync_state.status, "object_id": object_id}
    except Exception as exc:
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)
