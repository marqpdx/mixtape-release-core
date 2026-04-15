from __future__ import annotations

import logging

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from stackroom.integration.adapters.leaf import LeafStackroomAdapter
from stackroom.integration.adapters.profile import UserProfileStackroomAdapter
from stackroom.integration.adapters.seed import SeedStackroomAdapter
from stackroom.integration.adapters.working_document import WorkingDocumentStackroomAdapter
from stackroom.integration.adapters.writing_piece import WritingPieceStackroomAdapter
from stackroom.integration.modes import MODE_LOCAL, get_integration_mode
from stackroom.models import StackroomSyncState

logger = logging.getLogger(__name__)

_ADAPTERS = [
    LeafStackroomAdapter(),
    UserProfileStackroomAdapter(),
    SeedStackroomAdapter(),
    WorkingDocumentStackroomAdapter(),
    WritingPieceStackroomAdapter(),
]


def _get_adapter(obj):
    for adapter in _ADAPTERS:
        if adapter.supports(obj):
            return adapter
    raise ValueError(f"No Stackroom adapter registered for {obj.__class__.__name__}")


def get_sync_state(obj, adapter_name: str | None = None):
    content_type = ContentType.objects.get_for_model(obj, for_concrete_model=False)
    queryset = StackroomSyncState.objects.filter(
        content_type=content_type,
        object_id=str(obj.pk),
    )
    if adapter_name:
        queryset = queryset.filter(adapter_name=adapter_name)
    return queryset.first()


def _get_or_create_sync_state(obj, adapter_name: str, *, mode: str):
    content_type = ContentType.objects.get_for_model(obj, for_concrete_model=False)
    sync_state, _ = StackroomSyncState.objects.get_or_create(
        content_type=content_type,
        object_id=str(obj.pk),
        adapter_name=adapter_name,
        defaults={
            "transport_mode": mode,
            "status": StackroomSyncState.STATUS_PENDING,
        },
    )
    return sync_state


def ingest_object(obj, *, reason: str, force: bool = False):
    adapter = _get_adapter(obj)
    mode = get_integration_mode()

    sync_state = _get_or_create_sync_state(obj, adapter.adapter_name, mode=mode)
    sync_state.transport_mode = mode

    if not adapter.should_reingest(sync_state, obj, force=force):
        if sync_state.transport_mode != mode:
            sync_state.transport_mode = mode
            sync_state.save(update_fields=["transport_mode", "updated_at"])
        return sync_state

    try:
        if sync_state.status != StackroomSyncState.STATUS_PENDING:
            sync_state.status = StackroomSyncState.STATUS_PENDING
            sync_state.last_error = ""
            sync_state.save(update_fields=["status", "last_error", "updated_at"])

        if mode != MODE_LOCAL:
            logger.info("Stackroom integration mode %s not implemented yet; falling back to local", mode)

        result = adapter.ingest_local(obj, sync_state, reason=reason)
        sync_state.status = result["status"]
        sync_state.last_ingested_at = timezone.now()
        sync_state.last_synced_hash = result.get("hash", "")
        sync_state.last_error = ""
        sync_state.stackroom_library_id = result.get("library_id")
        sync_state.stackroom_source_file_id = result.get("source_file_id")
        sync_state.stackroom_artifact_id = result.get("artifact_id")
        sync_state.metadata = result.get("metadata", {})
        sync_state.transport_mode = mode
        sync_state.save()
        return sync_state
    except Exception as exc:
        logger.exception("Stackroom ingest failed for %s (%s)", adapter.adapter_name, obj.pk)
        sync_state.status = StackroomSyncState.STATUS_FAILED
        sync_state.last_error = str(exc)
        sync_state.transport_mode = mode
        sync_state.save(update_fields=["status", "last_error", "transport_mode", "updated_at"])
        raise


def ingest_object_safely(obj, *, reason: str, force: bool = False):
    try:
        return ingest_object(obj, reason=reason, force=force)
    except Exception:
        return None


def enqueue_ingest_object(obj, *, reason: str, force: bool = False):
    adapter = _get_adapter(obj)
    mode = get_integration_mode()
    sync_state = _get_or_create_sync_state(obj, adapter.adapter_name, mode=mode)
    sync_state.status = StackroomSyncState.STATUS_PENDING
    sync_state.last_error = ""
    sync_state.transport_mode = mode
    sync_state.save(update_fields=["status", "last_error", "transport_mode", "updated_at"])

    from stackroom.tasks.integration import ingest_object_task

    ingest_object_task.delay(
        content_type_id=sync_state.content_type_id,
        object_id=sync_state.object_id,
        adapter_name=adapter.adapter_name,
        reason=reason,
        force=force,
    )
    return sync_state


def deactivate_object(obj, *, reason: str):
    adapter = _get_adapter(obj)
    sync_state = get_sync_state(obj, adapter.adapter_name)
    if sync_state is None:
        return None
    mode = get_integration_mode()
    try:
        result = adapter.deactivate_local(obj, sync_state, reason=reason)
        sync_state.status = result["status"]
        sync_state.last_error = ""
        sync_state.metadata = result.get("metadata", {})
        sync_state.transport_mode = mode
        sync_state.save(update_fields=["status", "last_error", "metadata", "transport_mode", "updated_at"])
        return sync_state
    except Exception as exc:
        logger.exception("Stackroom deactivate failed for %s (%s)", adapter.adapter_name, obj.pk)
        sync_state.status = StackroomSyncState.STATUS_FAILED
        sync_state.last_error = str(exc)
        sync_state.transport_mode = mode
        sync_state.save(update_fields=["status", "last_error", "transport_mode", "updated_at"])
        raise


def deactivate_object_safely(obj, *, reason: str):
    try:
        return deactivate_object(obj, reason=reason)
    except Exception:
        return None


def enqueue_deactivate_object(obj, *, reason: str):
    adapter = _get_adapter(obj)
    mode = get_integration_mode()
    sync_state = _get_or_create_sync_state(obj, adapter.adapter_name, mode=mode)
    sync_state.status = StackroomSyncState.STATUS_PENDING
    sync_state.last_error = ""
    sync_state.transport_mode = mode
    sync_state.save(update_fields=["status", "last_error", "transport_mode", "updated_at"])

    from stackroom.tasks.integration import deactivate_object_task

    deactivate_object_task.delay(
        content_type_id=sync_state.content_type_id,
        object_id=sync_state.object_id,
        adapter_name=adapter.adapter_name,
        reason=reason,
    )
    return sync_state
