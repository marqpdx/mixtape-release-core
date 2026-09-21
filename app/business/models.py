# business/models.py

import uuid

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from fundamentals.bases import BaseModel


User = get_user_model()


class Supplier(BaseModel):
    """
    A named supplier or vendor associated with a group.
    Created explicitly or on first reference from a 'need_more' command.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    sponsor_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="business_suppliers",
    )
    sponsor_object_id = models.UUIDField()
    sponsor = GenericForeignKey("sponsor_content_type", "sponsor_object_id")

    name = models.CharField(max_length=255)
    contact_info = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_suppliers",
    )

    class Meta(BaseModel.Meta):
        ordering = ["name"]
        indexes = [
            models.Index(
                fields=["sponsor_content_type", "sponsor_object_id", "name"],
                name="business_supplier_sponsor_idx",
            ),
        ]

    def __str__(self):
        return self.name


class SupplyRequestStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ORDERED = "ordered", "Ordered"
    RECEIVED = "received", "Received"


class SupplyRequest(BaseModel):
    """
    A 'we need more X' record created by a 'need_more' agent command.
    Optionally linked to a known Supplier.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    sponsor_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="business_supply_requests",
    )
    sponsor_object_id = models.UUIDField()
    sponsor = GenericForeignKey("sponsor_content_type", "sponsor_object_id")

    item_name = models.CharField(max_length=255)
    quantity_note = models.CharField(max_length=255, blank=True, default="")
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supply_requests",
    )
    status = models.CharField(
        max_length=20,
        choices=SupplyRequestStatus.choices,
        default=SupplyRequestStatus.PENDING,
    )

    # Initiative linkage — set when command was fired from an initiative context
    initiative_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="business_supply_request_initiatives",
    )
    initiative_object_id = models.UUIDField(null=True, blank=True)

    raw_input = models.TextField(blank=True, default="")
    parsed_metadata = models.JSONField(default=dict, blank=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_supply_requests",
    )

    class Meta(BaseModel.Meta):
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["sponsor_content_type", "sponsor_object_id", "-created_at"],
                name="business_supplyreq_sponsor_idx",
            ),
            models.Index(
                fields=["status", "-created_at"],
                name="business_supplyreq_status_idx",
            ),
        ]

    def __str__(self):
        supplier_label = f" from {self.supplier.name}" if self.supplier_id else ""
        return f"{self.item_name}{supplier_label} [{self.status}]"


class FixItemStatus(models.TextChoices):
    OPEN = "open", "Open"
    IN_PROGRESS = "in_progress", "In Progress"
    RESOLVED = "resolved", "Resolved"


class FixItem(BaseModel):
    """
    A repair or maintenance issue created by a 'fix' agent command.
    Distinct from a Task — tracks something broken that needs fixing.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    sponsor_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="business_fix_items",
    )
    sponsor_object_id = models.UUIDField()
    sponsor = GenericForeignKey("sponsor_content_type", "sponsor_object_id")

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=FixItemStatus.choices,
        default=FixItemStatus.OPEN,
    )

    # Initiative linkage
    initiative_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="business_fix_item_initiatives",
    )
    initiative_object_id = models.UUIDField(null=True, blank=True)

    raw_input = models.TextField(blank=True, default="")
    parsed_metadata = models.JSONField(default=dict, blank=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_fix_items",
    )

    class Meta(BaseModel.Meta):
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["sponsor_content_type", "sponsor_object_id", "-created_at"],
                name="business_fixitem_sponsor_idx",
            ),
            models.Index(
                fields=["status", "-created_at"],
                name="business_fixitem_status_idx",
            ),
        ]

    def __str__(self):
        return f"{self.title} [{self.status}]"


class Client(BaseModel):
    """
    A Mindful Brilliance client — an organisation we have a direct relationship
    with, invoice, and do knowledge-building work for.

    Always linked to a Group (the operational unit) and optionally to the
    BusinessProspect that became this client via the convert flow.

    Contact fields are intentionally here, not on Group or GroupContext.
    Group = structural unit. GroupContext = AI prompt substrate.
    Client = relationship / CRM layer.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    group = models.OneToOneField(
        "groups.Group",
        on_delete=models.CASCADE,
        related_name="client",
    )
    prospect = models.OneToOneField(
        "prospects.BusinessProspect",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="client",
    )

    # Contact info — comes from prospect on conversion, editable after
    primary_contact_name = models.CharField(max_length=200, blank=True)
    primary_contact_email = models.EmailField(blank=True)
    primary_contact_phone = models.CharField(max_length=50, blank=True)
    website = models.URLField(blank=True)
    business_type = models.CharField(max_length=200, blank=True)

    # Relationship notes (internal, not shown to client)
    contract_notes = models.TextField(blank=True)
    billing_notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_clients",
    )

    class Meta(BaseModel.Meta):
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.group.title} (client)"
