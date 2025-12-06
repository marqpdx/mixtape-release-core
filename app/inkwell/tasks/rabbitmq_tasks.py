# inkwell/tasks/rabbitmq_tasks.py

import logging

import pika
import requests
from celery import shared_task
from django.conf import settings
from django.core.cache import cache


logger = logging.getLogger(__name__)

# Cache keys for controlling polling
POLLING_ACTIVE_KEY = "rabbitmq_polling_active"
POLLING_TASK_ID_KEY = "rabbitmq_polling_task_id"

@shared_task(bind=True)
def send_task_to_fastapi(self, task_id):
    """
    Step 1: Send task to FastAPI and start polling for results
    """
    logger.info(" [task] Sending request to FastAPI for task %s", task_id)

    fastapi_url = f"{settings.INKWELL_BASE_URL}/generate_task"
    response = requests.post(fastapi_url, json={"task_id": task_id}, timeout=30)

    if response.status_code == 200:
        logger.info(" [task] Task %s started successfully!", task_id)

        # Start polling for this specific task
        start_rabbitmq_polling.delay(task_id)

        return {"status": "success", "task_id": task_id, "message": "Task started and polling initiated"}
    logger.error(" [task] Failed to start task {task_id} on FastAPI: %s", response.text)
    return {"status": "error", "task_id": task_id, "error": response.text}

@shared_task(bind=True)
def start_rabbitmq_polling(self, expected_task_id):
    """
    Step 2: Start polling RabbitMQ for results from FastAPI
    """
    # Set polling as active in cache
    cache.set(POLLING_ACTIVE_KEY, True, timeout=300)  # 5 minute timeout
    cache.set(POLLING_TASK_ID_KEY, expected_task_id, timeout=300)

    logger.info("🔄 [polling] Starting to poll for task {expected_task_id}")

    # Start the polling loop
    poll_rabbitmq_results.delay(expected_task_id, max_attempts=60)  # Poll for up to 5 minutes

@shared_task(bind=True)
def poll_rabbitmq_results(self, expected_task_id, max_attempts=60, attempt=1):
    """
    Step 3: Poll RabbitMQ queue for task results
    """
    # Check if polling should continue
    if not cache.get(POLLING_ACTIVE_KEY):
        logger.info("🛑 [polling] Polling stopped for task {expected_task_id}")
        return {"status": "stopped", "task_id": expected_task_id}

    if attempt > max_attempts:
        logger.info("⏰ [polling] Max attempts reached for task {expected_task_id}")
        stop_rabbitmq_polling(expected_task_id)
        return {"status": "timeout", "task_id": expected_task_id}

    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
        channel = connection.channel()

        # Ensure queue exists
        channel.queue_declare(queue="task_results", durable=True)

        # Try to get a message
        method_frame, header_frame, body = channel.basic_get(queue="task_results", auto_ack=False)

        if method_frame:
            message = body.decode("utf-8")
            logger.info("📩 [polling] Received message: {message}")

            # Parse the message (format: "task_id:result")
            try:
                received_task_id, result = message.split(":", 1)

                if received_task_id == expected_task_id:
                    # This is our message!
                    logger.info(" [polling] Found result for task {expected_task_id}: %s", result)

                    # Acknowledge the message
                    channel.basic_ack(delivery_tag=method_frame.delivery_tag)
                    connection.close()

                    # Process the result
                    process_task_result.delay(expected_task_id, result)

                    # Stop polling
                    stop_rabbitmq_polling(expected_task_id)

                    return {"status": "success", "task_id": expected_task_id, "result": result}
                # Not our message, put it back and continue
                logger.info("📨 [polling] Message for different task ({received_task_id}), continuing to poll...")
                channel.basic_nack(delivery_tag=method_frame.delivery_tag, requeue=True)
                connection.close()
            except ValueError:
                logger.error(" [polling] Invalid message format: %s", message)
                channel.basic_ack(delivery_tag=method_frame.delivery_tag)  # Remove bad message
                connection.close()
        else:
            # No message, close connection
            connection.close()

        # Schedule next poll in 5 seconds
        logger.info("🔄 [polling] No result yet for task {expected_task_id}, attempt {attempt}/{max_attempts}")
        poll_rabbitmq_results.apply_async(
            args=[expected_task_id, max_attempts, attempt + 1],
            countdown=5  # Wait 5 seconds before next poll
        )

    except Exception as e:
        logger.error(" [polling] Error polling RabbitMQ: %s", e)
        # Retry after 10 seconds on error
        poll_rabbitmq_results.apply_async(
            args=[expected_task_id, max_attempts, attempt + 1],
            countdown=10
        )

@shared_task(bind=True)
def process_task_result(self, task_id, result):
    """
    Step 4: Process the result and save to database
    """
    logger.info("💾 [processing] Processing result for task {task_id}: {result}")

    # TODO: Add your database saving logic here
    # Example:
    # from myapp.models import TaskResult
    # TaskResult.objects.create(task_id=task_id, result=result, status='completed')

    # For now, just log it
    logger.info(" [processing] Task {task_id} result saved to database: %s", result)

    return {"status": "processed", "task_id": task_id, "result": result}

def stop_rabbitmq_polling(task_id):
    """
    Helper function to stop polling
    """
    cache.delete(POLLING_ACTIVE_KEY)
    cache.delete(POLLING_TASK_ID_KEY)
    logger.info("🛑 [polling] Stopped polling for task {task_id}")

@shared_task(bind=True)
def manual_stop_polling(self):
    """
    Manual task to stop polling if needed
    """
    active_task_id = cache.get(POLLING_TASK_ID_KEY, "unknown")
    stop_rabbitmq_polling(active_task_id)
    return {"status": "stopped", "task_id": active_task_id}
