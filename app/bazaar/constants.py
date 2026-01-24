# bazaar/constants.py

"""
Bazaar enums and constants.

These define the canonical choices for Bazaar models.
"""

from django.db import models


class OfferingShape(models.TextChoices):
    """
    Shapes describe fulfillment semantics, not UI categories.
    Shape determines required references, fulfillment expectations, and validation rules.
    """
    SERVICE = "service", "Service"
    EVENT = "event", "Event"
    PROGRAM = "program", "Program"
    PRODUCT = "product", "Product"


class OfferingStatus(models.TextChoices):
    """Offering lifecycle status."""
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    UNAVAILABLE = "unavailable", "Unavailable"
    ARCHIVED = "archived", "Archived"


class OfferingVisibility(models.TextChoices):
    """Who can see and purchase this offering."""
    PUBLIC = "public", "Public"
    MEMBERS_ONLY = "members_only", "Members only"
    UNLISTED = "unlisted", "Unlisted"


class FulfillmentType(models.TextChoices):
    """
    How an offering's promise is completed.
    May differ from shape in some cases (e.g., event with manual fulfillment).
    """
    MANUAL = "manual", "Manual"
    EVENT = "event", "Event"
    DIGITAL = "digital", "Digital"
    PROGRAM = "program", "Program"


class OrderStatus(models.TextChoices):
    """
    Canonical order lifecycle.
    Flow: pending → confirmed → fulfilling → delivered → completed
    """
    PENDING = "pending", "Pending"
    CONFIRMED = "confirmed", "Confirmed"
    FULFILLING = "fulfilling", "Fulfilling"
    DELIVERED = "delivered", "Delivered"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class ProductStatus(models.TextChoices):
    """Product asset lifecycle (separate from OfferingStatus)."""
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"
    RETIRED = "retired", "Retired"


class ProductType(models.TextChoices):
    """Types of products that can be created."""
    PHYSICAL = "physical", "Physical"
    DIGITAL = "digital", "Digital"
    SERVICE = "service", "Service"
    BUNDLE = "bundle", "Bundle"


class FulfillmentActorType(models.TextChoices):
    """Who performed a fulfillment action."""
    VENDOR = "vendor", "Vendor"
    SYSTEM = "system", "System"


class FulfillmentEventType(models.TextChoices):
    """Types of fulfillment events for audit trail."""
    STARTED = "started", "Started"
    DELIVERED = "delivered", "Delivered"
    AUTO_DELIVERED = "auto_delivered", "Auto delivered"
