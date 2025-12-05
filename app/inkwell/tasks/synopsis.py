# inkwell/tasks/synopsis.py

import logging


logger = logging.getLogger(__name__)

import os

import requests  # To make the HTTP call to FastAPI
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from django.conf import settings

from inkwell.models import SuggestedAsset


# Define the Redis connection (ensure Redis is properly configured)
# redis_client = redis.StrictRedis(host='localhost', port=6379, db=0)

# pubsub = redis_client.pubsub()
# pubsub.subscribe("synopsis_channel")

# for message in pubsub.listen():
#     logger.info("Received message: {message}")






@shared_task(bind=True, max_retries=5, default_retry_delay=10)  # ⏳ 10s base delay
def generate_synopsis_task(self, asset_id):

    logger.error(" [task] generating synopsis is ready")

    try:
        logger.info(" [task] Received request to generate synopsis for asset %s", asset_id)

        # asset = SuggestedAsset.objects.get(id=asset_id)
        asset = SuggestedAsset.objects.select_related("gutenberg_info").get(id=asset_id)


        # ⛔ Skip if asset was deleted
        if hasattr(asset, "deleted_asset"):
            logger.info("⛔ [task] Skipping synopsis for asset {asset_id} — marked as deleted")
            return

        # ⛔ Skip if already generating or done
        if asset.synopsis_status == "generating":
            logger.info(" [task] Skipping asset %s — already generating", asset_id)
            return

        if asset.synopsis and asset.synopsis_status == "complete":
            logger.info(" [task] Skipping asset %s — synopsis already complete", asset_id)
            return

        # Mark as pending
        asset.synopsis_status = "pending"
        asset.save()
        logger.info(" [task] Status set to 'pending' for: %s", asset.title or asset.id)

        # Make the HTTP call to FastAPI (LLM service)
        # Include RabbitMQ connection info so FastAPI can publish results back
        fastapi_url = f"{settings.FASTAPI_LLM_URL}/generate_synopsis"

        rabbitmq_broker = os.getenv("CELERY_BROKER_URL", "amqp://guest:guest@127.0.0.1:5672//")

        payload = {
            "asset_id": asset.id,
            "asset_url": asset.gutenberg_info.text_url,
            "rabbitmq": {
                "broker_url": rabbitmq_broker,
                "queue_name": "synopsis_results",
                "routing_key": "synopsis_results"
            }
        }

        response = requests.post(fastapi_url, json=payload, timeout=30)

        if response.status_code == 200:
            logger.info(" [task] Synopsis generation request sent for: %s", asset.title or asset.id)

            # Publish to Redis that the synopsis generation task has been triggered
            # redis_client.publish("synopsis_channel", f"{asset_id}:pending")
            logger.info(" [task] Synopsis generation request sent successfully for: %s", asset.title or asset.id)
        else:
            logger.error(" [task] Failed to generate synopsis for asset {asset_id}: %s", response.text)
            asset.synopsis_status = "failed"
            asset.save()

    except SuggestedAsset.DoesNotExist:
        logger.error(" Asset not found: %s", asset_id)

    except Exception as e:
        logger.error(" Retryable synopsis error for asset {asset_id}: %s", e)
        try:
            # ⏳ exponential backoff
            # 🛑 Double-check before retrying
            asset.refresh_from_db()
            if hasattr(asset, "deleted_asset"):
                logger.info("⛔ [task] Aborting retry: asset {asset_id} is now deleted.")
                return

            delay = 2 ** self.request.retries * 10
            logger.info(" [task] Retrying in {delay}s (retry #%s)...", self.request.retries + 1)
            self.retry(exc=e, countdown=delay)
        except MaxRetriesExceededError:
            logger.error(" [task] Max retries exceeded for asset %s", asset_id)
            try:
                asset = SuggestedAsset.objects.get(id=asset_id)
                asset.synopsis_status = "failed"
                asset.save()
                logger.error(" [task] Marked asset %s as failed", asset_id)
            except SuggestedAsset.DoesNotExist:
                logger.error(" [task] Asset %s vanished before it could be marked failed", asset_id)


@shared_task(name="inkwell.tasks.synopsis.process_synopsis_result")
def process_synopsis_result(asset_id, synopsis, status="complete"):
    """
    RabbitMQ Consumer Task: Processes synopsis results published by FastAPI

    This task is triggered when FastAPI publishes to the 'synopsis_results' queue
    after completing LLM synopsis generation.

    Args:
        asset_id: ID of the SuggestedAsset to update
        synopsis: Generated synopsis text from LLM
        status: Status ('complete' or 'failed')
    """
    try:
        logger.info("[synopsis_result] Received synopsis result for asset %s", asset_id)

        asset = SuggestedAsset.objects.get(id=asset_id)
        asset.synopsis = synopsis
        asset.synopsis_status = status
        asset.save()

        logger.info("[synopsis_result] Successfully saved synopsis for: %s", asset.title)
        return {"status": "saved", "asset_id": asset_id, "title": asset.title}

    except SuggestedAsset.DoesNotExist:
        logger.error("[synopsis_result] Asset %s not found when trying to save synopsis", asset_id)
        return {"status": "error", "error": "Asset not found"}

    except Exception as e:
        logger.error("[synopsis_result] Failed to save synopsis for asset %s: %s", asset_id, e, exc_info=True)
        raise  # Re-raise to trigger Celery retry if configured


