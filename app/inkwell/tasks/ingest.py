# ai/tasks/ingest.py

from celery import shared_task
from django.utils import timezone


@shared_task(name="ai.tasks.ingest.ingest_approved_asset_task", acks_late=False, bind=True)
def ingest_approved_asset_task(self, asset_id):
    logger.info("👋 TASK STARTED: ingest_approved_asset_task({asset_id})")

    from inkwell.config.ai_config import configure_embedding
    from inkwell.config.constants import DEFAULT_COLLECTION_NAME
    from inkwell.models import SuggestedAsset
    from inkwell.scripts.ingest_approved_asset import ingest_approved_asset
    from inkwell.scripts.utils import get_index

    configure_embedding()

    asset = SuggestedAsset.objects.get(id=asset_id)
    asset.ingestion_status = "processing"
    asset.ingestion_started_at = timezone.now()
    asset.save()

    index = get_index(DEFAULT_COLLECTION_NAME)

    try:
        result = ingest_approved_asset(asset, index)

        if result["success"]:
            asset.ingestion_status = "complete"
            asset.ingestion_completed_at = timezone.now()
            asset.save()
        else:
            asset.ingestion_status = "failed"
            asset.notes = result["error"]
            asset.save()
            raise self.retry(exc=Exception(result["error"]), countdown=60, max_retries=3)

    except Exception as e:
        asset.ingestion_status = "failed"
        asset.notes = str(e)
        asset.save()
        raise self.retry(exc=e, countdown=60, max_retries=3)
