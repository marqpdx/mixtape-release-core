from celery import shared_task

from ops.models import OpsSnapshot
from ops.services.application import persist_application_snapshot
from ops.services.postgres import persist_postgres_snapshot


@shared_task(bind=True, queue="polling")
def collect_postgres_snapshot(self) -> dict:
    snapshot = persist_postgres_snapshot(source=OpsSnapshot.SOURCE_SCHEDULED)
    return {
        "snapshot_id": snapshot.id,
        "server_name": snapshot.server_name,
        "subsystem": snapshot.subsystem,
        "status": snapshot.status,
        "collected_at": snapshot.collected_at.isoformat(),
    }


@shared_task(bind=True, queue="polling")
def collect_application_snapshot(self) -> dict:
    snapshot = persist_application_snapshot(source=OpsSnapshot.SOURCE_SCHEDULED)
    return {
        "snapshot_id": snapshot.id,
        "server_name": snapshot.server_name,
        "subsystem": snapshot.subsystem,
        "status": snapshot.status,
        "collected_at": snapshot.collected_at.isoformat(),
    }
