# In your Django views.py

import uuid

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from inkwell.tasks.rabbitmq_tasks import manual_stop_polling, send_task_to_fastapi


@api_view(["POST"])
@permission_classes([AllowAny])
def trigger_llm_task(request):
    """
    Endpoint to trigger the LLM task process
    """
    # Generate a unique task ID
    task_id = str(uuid.uuid4())

    logger.info("🚀 [api] Starting LLM task with ID: {task_id}")

    # Trigger the entire process
    celery_task = send_task_to_fastapi.delay(task_id)

    return Response({
        "status": "success",
        "task_id": task_id,
        "celery_task_id": celery_task.id,
        "message": "LLM task started successfully"
    })

@api_view(["POST"])
@permission_classes([AllowAny])
def stop_polling(request):
    """
    Emergency endpoint to stop polling
    """
    manual_stop_polling.delay()
    return Response({
        "status": "success",
        "message": "Polling stopped"
    })

@api_view(["GET"])
@permission_classes([AllowAny])
def task_status(request):
    """
    Check current polling status
    """
    from django.core.cache import cache

    is_polling = cache.get("rabbitmq_polling_active", False)
    current_task = cache.get("rabbitmq_polling_task_id", None)

    return Response({
        "is_polling": is_polling,
        "current_task_id": current_task
    })
