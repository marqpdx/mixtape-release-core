from __future__ import annotations

import json
import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def generate_snapshot(self, library_id: str) -> None:
    """Build a manifest snapshot for the given library and deliver it per SnapshotConfig."""
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage

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

        logger.info("generate_snapshot: complete library=%s snapshot=%s", library_id, snapshot.id)

    except Exception:
        snapshot.status = 'failed'
        snapshot.save(update_fields=['status', 'updated_at'])
        logger.exception("generate_snapshot: delivery failed library=%s snapshot=%s", library_id, snapshot.id)
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
