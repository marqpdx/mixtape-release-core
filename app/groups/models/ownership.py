# groups/models/ownership.py
"""
OwnershipChangeRequest — time-delayed ownership changes for groups.

All ownership mutations (add/remove/demote/transfer owner, set escrow)
go through a request that executes after a configurable delay,
giving other owners time to review and cancel.
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from fundamentals.bases import BaseModel


class OwnershipAction(models.TextChoices):
    ADD_OWNER = "ADD_OWNER", "Add Owner"
    REMOVE_OWNER = "REMOVE_OWNER", "Remove Owner"
    DEMOTE_OWNER = "DEMOTE_OWNER", "Demote Owner"
    TRANSFER_OWNERSHIP = "TRANSFER_OWNERSHIP", "Transfer Ownership"
    SET_ESCROW_OWNER = "SET_ESCROW_OWNER", "Set Escrow Owner"


class OwnershipRequestStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    CANCELED = "CANCELED", "Canceled"
    EXECUTED = "EXECUTED", "Executed"
    FAILED = "FAILED", "Failed"


class OwnershipChangeRequest(BaseModel):
    """
    A time-delayed request to change group ownership.

    Created by an active owner, executes automatically after
    group.ownership_change_delay_seconds (default 24h).
    Any owner can cancel a pending request before execution.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    group = models.ForeignKey(
        "groups.Group",
        on_delete=models.CASCADE,
        related_name="ownership_requests",
    )

    action = models.CharField(
        max_length=24,
        choices=OwnershipAction.choices,
    )

    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ownership_requests_targeting",
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ownership_requests_made",
    )

    execute_after = models.DateTimeField(
        help_text="Request will not execute before this time",
    )

    status = models.CharField(
        max_length=16,
        choices=OwnershipRequestStatus.choices,
        default=OwnershipRequestStatus.PENDING,
    )

    canceled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    canceled_at = models.DateTimeField(null=True, blank=True)

    executed_at = models.DateTimeField(null=True, blank=True)

    failure_reason = models.TextField(blank=True, default="")

    snapshot = models.JSONField(
        default=dict,
        blank=True,
        help_text="Snapshot of owner state at request time",
    )

    class Meta:
        db_table = "groups_ownershipchangerequest"
        indexes = [
            models.Index(fields=["status", "execute_after"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.action} → {self.target_user} in {self.group} ({self.status})"
