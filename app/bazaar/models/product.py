# bazaar/models/product.py

"""
Bazaar Product Model

A Product is a sponsor-owned asset created explicitly to be offered later.
Products can exist without being sold - they become transactable through Bazaar
only when one or more Offerings are created that reference them.
"""

from django.db import models

from fundamentals.models import BaseContent
from bazaar.constants import ProductStatus, ProductType


class Product(BaseContent):
    """
    A sponsor-owned asset created explicitly to be offered later.

    Inherits from BaseContent:
    - id (UUID primary key)
    - sponsor (polymorphic: Group, User, etc.)
    - title, summary, body, slug
    - author, submitted_by
    - tags, categories
    - published_at
    - created_at, updated_at, deleted_at
    """

    product_type = models.CharField(
        max_length=20,
        choices=ProductType.choices,
        default=ProductType.PHYSICAL,
    )

    # Optional: attach a primary media/file reference.
    # Flexible for now; assets app can formalize later.
    primary_file_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="Reference to primary file/media asset (UUID).",
    )

    # Physical goods (v0 intentionally minimal)
    requires_shipping = models.BooleanField(
        default=False,
        help_text="Whether this product requires physical shipping.",
    )

    status = models.CharField(
        max_length=20,
        choices=ProductStatus.choices,
        default=ProductStatus.ACTIVE,
        help_text="Asset lifecycle; does not imply it is currently offered.",
    )

    class Meta(BaseContent.Meta):
        verbose_name = "Bazaar Product"
        verbose_name_plural = "Bazaar Products"

    def __str__(self):
        return self.title or f"Product {self.pk}"
