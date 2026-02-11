# groups/tasks.py
"""
Celery tasks for the groups app.
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def execute_due_ownership_requests(self):
    """
    Periodic task: find and execute pending ownership requests
    whose delay has expired.

    Uses select_for_update(skip_locked=True) so multiple workers
    won't double-execute the same request.
    """
    from groups.models.ownership import OwnershipChangeRequest, OwnershipRequestStatus
    from groups.services.ownership import execute_ownership_request

    now = timezone.now()

    # Collect IDs under a short lock so we don't hold select_for_update
    # across long-running execute calls.
    with transaction.atomic():
        due_ids = list(
            OwnershipChangeRequest.objects
            .filter(
                status=OwnershipRequestStatus.PENDING,
                execute_after__lte=now,
            )
            .select_for_update(skip_locked=True)
            .values_list("pk", flat=True)
        )

    count = 0
    for request_id in due_ids:
        try:
            request = OwnershipChangeRequest.objects.get(pk=request_id)
            execute_ownership_request(request)
            count += 1
        except Exception:
            logger.exception(
                "Failed to execute ownership request %s", request_id
            )

    if count:
        logger.info("Executed %d ownership change request(s)", count)
