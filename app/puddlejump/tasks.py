from __future__ import annotations

import json
import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

_DEFAULT_TENANT_ID = getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", "00000000-0000-0000-0000-000000000001")
_DEFAULT_TENANT_NAMESPACE = getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", "platform:crossroads")


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def generate_snapshot(self, library_id: str, triggered_by_id: str | None = None) -> None:
    """Build a manifest snapshot for the given library and deliver it per SnapshotConfig."""
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage

    from initiatives.models import ActionRun, ActionRunExecutionMode, ActionRunInitiatorType, ActionRunStatus
    from puddlejump.models import Library, LibrarySnapshot, ManifestEvent, SnapshotConfig

    try:
        library = Library.objects.get(pk=library_id)
    except Library.DoesNotExist:
        logger.warning("generate_snapshot: library %s not found", library_id)
        return

    try:
        config = library.snapshot_config
    except SnapshotConfig.DoesNotExist:
        logger.warning("generate_snapshot: no SnapshotConfig for library %s", library_id)
        return

    if not config.is_enabled:
        return

    now = timezone.now()

    action_run = ActionRun.objects.create(
        tool_name="puddlejump.snapshot",
        status=ActionRunStatus.RUNNING,
        execution_mode=ActionRunExecutionMode.LOCAL,
        tenant_id=_DEFAULT_TENANT_ID,
        tenant_namespace=_DEFAULT_TENANT_NAMESPACE,
        initiator_type=ActionRunInitiatorType.HUMAN if triggered_by_id else ActionRunInitiatorType.MODEL,
        initiator_id=triggered_by_id or "system:beat-scheduler",
        request_payload={"library_id": library_id, "frequency": config.frequency},
        started_at=now,
    )

    events = (
        ManifestEvent.objects
        .filter(library=library, created_at__lte=now)
        .order_by('library_item_id', 'created_at')
        .select_related('version')
    )

    manifest: dict = {}
    for event in events:
        item_id = str(event.library_item_id) if event.library_item_id else None
        if item_id is None:
            continue
        if event.event_type == 'delete':
            manifest.pop(item_id, None)
        else:
            manifest[item_id] = {
                'id': item_id,
                'path': event.path,
                'version_id': str(event.version_id) if event.version_id else None,
                'hash': event.hash_sha256,
                'size_bytes': event.version.size_bytes if event.version else None,
                'event_type': event.event_type,
            }

    files = list(manifest.values())
    total_size = sum(f['size_bytes'] or 0 for f in files)

    snapshot = LibrarySnapshot.objects.create(
        library=library,
        snapshot_at=now,
        manifest_json={'library_id': str(library.id), 'as_of': now.isoformat(), 'files': files},
        file_count=len(files),
        total_size_bytes=total_size,
        delivered_to=config.endpoint_type,
        status='pending',
    )

    try:
        if config.endpoint_type == 'internal':
            key = f"snapshots/{library.id}/{snapshot.id}.json"
            default_storage.save(key, ContentFile(json.dumps(snapshot.manifest_json).encode()))
            snapshot.delivery_key = key
        elif config.endpoint_type == 's3':
            logger.warning("generate_snapshot: s3 delivery not yet implemented for library %s", library_id)
            snapshot.delivery_key = ''

        snapshot.status = 'complete'
        snapshot.save(update_fields=['status', 'delivery_key', 'updated_at'])

        config.last_snapshot_at = now
        config.save(update_fields=['last_snapshot_at', 'updated_at'])

        old_ids = list(
            LibrarySnapshot.objects
            .filter(library=library, status='complete')
            .order_by('-snapshot_at')
            .values_list('id', flat=True)[config.retain_count:]
        )
        if old_ids:
            LibrarySnapshot.objects.filter(id__in=old_ids).delete()

        action_run.status = ActionRunStatus.SUCCEEDED
        action_run.result_payload = {"snapshot_id": str(snapshot.id), "file_count": len(files)}
        action_run.completed_at = timezone.now()
        action_run.save(update_fields=["status", "result_payload", "completed_at", "updated_at"])
        logger.info("generate_snapshot: complete library=%s snapshot=%s", library_id, snapshot.id)

    except Exception:
        snapshot.status = 'failed'
        snapshot.save(update_fields=['status', 'updated_at'])
        action_run.status = ActionRunStatus.FAILED
        action_run.error_payload = {"library_id": library_id, "snapshot_id": str(snapshot.id)}
        action_run.completed_at = timezone.now()
        action_run.save(update_fields=["status", "error_payload", "completed_at", "updated_at"])
        logger.exception("generate_snapshot: delivery failed library=%s snapshot=%s", library_id, snapshot.id)
        raise


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def ingest_library_item(self, library_item_id: str, triggered_by_id: str | None = None) -> None:
    """Ingest a library item's text into Stackroom IR. Fired async after upload."""
    from django.core.files.storage import default_storage

    from initiatives.models import ActionRun, ActionRunExecutionMode, ActionRunInitiatorType, ActionRunStatus
    from stackroom_client import ingest_text
    from puddlejump.models import LibraryItem

    try:
        item = LibraryItem.objects.select_related('library').get(pk=library_item_id)
    except LibraryItem.DoesNotExist:
        logger.warning("ingest_library_item: item %s not found", library_item_id)
        return

    action_run = ActionRun.objects.create(
        tool_name="puddlejump.ingest",
        status=ActionRunStatus.RUNNING,
        execution_mode=ActionRunExecutionMode.LOCAL_RETRIEVAL,
        tenant_id=_DEFAULT_TENANT_ID,
        tenant_namespace=_DEFAULT_TENANT_NAMESPACE,
        initiator_type=ActionRunInitiatorType.HUMAN if triggered_by_id else ActionRunInitiatorType.MODEL,
        initiator_id=triggered_by_id or "system:sync-upload",
        request_payload={"library_item_id": library_item_id, "path": item.folder_path},
        started_at=timezone.now(),
    )

    try:
        f = default_storage.open(item.s3_key)
        content = f.read()
        f.close()
        text = content.decode('utf-8')

        result = ingest_text(
            library_id=item.library.id,
            source_path=item.folder_path,
            filename=item.filename,
            text=text,
        )
        source_file_id = result.get('source_file_id')
        if source_file_id:
            item.source_file_id = source_file_id
            item.save(update_fields=['source_file_id', 'updated_at'])

        action_run.status = ActionRunStatus.SUCCEEDED
        action_run.result_payload = {"source_file_id": source_file_id, "path": item.folder_path}
        action_run.completed_at = timezone.now()
        action_run.save(update_fields=["status", "result_payload", "completed_at", "updated_at"])
        logger.info("ingest_library_item: complete item=%s source_file_id=%s", library_item_id, source_file_id)

    except Exception:
        action_run.status = ActionRunStatus.FAILED
        action_run.error_payload = {"library_item_id": library_item_id}
        action_run.completed_at = timezone.now()
        action_run.save(update_fields=["status", "error_payload", "completed_at", "updated_at"])
        logger.exception("ingest_library_item: failed for item=%s", library_item_id)
        raise


@shared_task
def run_scheduled_snapshots() -> None:
    """Beat task — fire generate_snapshot for any library whose schedule is due."""
    from puddlejump.models import SnapshotConfig

    now = timezone.now()
    configs = SnapshotConfig.objects.filter(is_enabled=True).exclude(frequency='on_transaction')

    for config in configs:
        last = config.last_snapshot_at
        freq = config.frequency

        due = (
            last is None
            or (freq == 'hourly' and now - last >= timedelta(hours=1))
            or (freq == 'daily' and now - last >= timedelta(days=1))
            or (freq == 'weekly' and now - last >= timedelta(weeks=1))
        )

        if due:
            generate_snapshot.delay(str(config.library_id))
