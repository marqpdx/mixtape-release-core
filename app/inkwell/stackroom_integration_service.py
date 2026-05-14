# inkwell/stackroom_integration_service.py
#
# Orchestrates Django → Stackroom ingest and deactivation.
# Called by Celery tasks; never called directly from views or signals.

from __future__ import annotations

import logging
from uuid import UUID

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from inkwell.models import StackroomSyncState
from inkwell.stackroom_adapters import get_adapter
from inkwell.stackroom_http_client import StackroomClientError, delete_source_file, ingest_text

logger = logging.getLogger(__name__)


def _get_or_create_sync_state(obj, adapter_name: str) -> StackroomSyncState:
    ct = ContentType.objects.get_for_model(obj, for_concrete_model=False)
    sync_state, _ = StackroomSyncState.objects.get_or_create(
        content_type=ct,
        object_id=str(obj.pk),
        adapter_name=adapter_name,
        defaults={"status": StackroomSyncState.STATUS_PENDING},
    )
    return sync_state


def ingest_object(obj, *, reason: str, force: bool = False) -> StackroomSyncState:
    adapter = get_adapter(obj)
    sync_state = _get_or_create_sync_state(obj, adapter.adapter_name)

    if not adapter.should_reingest(sync_state, obj, force=force):
        return sync_state

    sync_state.status = StackroomSyncState.STATUS_PENDING
    sync_state.last_error = ""
    sync_state.save(update_fields=["status", "last_error", "updated_at"])

    try:
        text = adapter.build_text(obj)
        if not text.strip():
            logger.info("Stackroom ingest skipped — empty text: %s %s", adapter.adapter_name, obj.pk)
            return sync_state

        library_id = adapter.get_library_id(obj)
        result = ingest_text(
            library_id=library_id,
            source_path=adapter.get_source_path(obj),
            filename=adapter.get_filename(obj),
            text=text,
        )

        sync_state.status = StackroomSyncState.STATUS_SYNCED
        sync_state.last_ingested_at = timezone.now()
        sync_state.last_synced_hash = result.get("hash_sha256", adapter.current_hash(obj))
        sync_state.stackroom_library_id = library_id
        if result.get("source_file_id"):
            sync_state.stackroom_source_file_id = UUID(result["source_file_id"])
        sync_state.last_error = ""
        sync_state.metadata = {**(sync_state.metadata or {}), "reason": reason}
        sync_state.save(update_fields=[
            "status", "last_ingested_at", "last_synced_hash",
            "stackroom_library_id", "stackroom_source_file_id",
            "last_error", "metadata", "updated_at",
        ])

    except StackroomClientError as exc:
        logger.warning("Stackroom ingest failed: %s %s — %s", adapter.adapter_name, obj.pk, exc)
        sync_state.status = StackroomSyncState.STATUS_FAILED
        sync_state.last_error = str(exc)
        sync_state.save(update_fields=["status", "last_error", "updated_at"])

    return sync_state


def deactivate_object(obj, *, reason: str) -> StackroomSyncState | None:
    adapter = get_adapter(obj)
    ct = ContentType.objects.get_for_model(obj, for_concrete_model=False)
    sync_state = StackroomSyncState.objects.filter(
        content_type=ct,
        object_id=str(obj.pk),
        adapter_name=adapter.adapter_name,
    ).first()

    if sync_state is None:
        return None

    if sync_state.stackroom_source_file_id:
        try:
            delete_source_file(sync_state.stackroom_source_file_id)
        except StackroomClientError as exc:
            logger.warning(
                "Stackroom deactivate failed: %s %s — %s", adapter.adapter_name, obj.pk, exc
            )

    sync_state.status = StackroomSyncState.STATUS_DEACTIVATED
    sync_state.metadata = {**(sync_state.metadata or {}), "deactivation_reason": reason}
    sync_state.save(update_fields=["status", "metadata", "updated_at"])
    return sync_state
