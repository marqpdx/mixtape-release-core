# groups/models/decorators/catalog.py

"""
Decorator catalog models.
Define available decorators that can be assigned to groups and memberships.
"""

from django.contrib.postgres.fields import ArrayField
from django.db import models

from ..dec_enums import DecoratorCategory


class GroupDecorator(models.Model):
    """
    Catalog of available group decorators.
    Defines capabilities, identities, and policies that can be applied to groups.

    Examples:
    - isA__Band (identity)
    - can__HostEvents (capability)
    - policy__InviteOnly (policy)
    """

    code = models.SlugField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="Unique code (e.g., 'isA__Band', 'can__HostEvents')"
    )

    category = models.CharField(
        max_length=20,
        choices=DecoratorCategory.choices,
        db_index=True,
        help_text="Category: identity, capability, or policy"
    )

    label = models.CharField(
        max_length=255,
        help_text="Human-readable label"
    )

    description = models.TextField(
        blank=True,
        help_text="Detailed description of what this decorator does"
    )

    valid_for_types = ArrayField(
        models.CharField(max_length=20),
        default=list,
        blank=True,
        help_text="Group types this decorator can be applied to (empty = all types)"
    )

    # Decorator relationships
    implies = models.ManyToManyField(
        "self",
        symmetrical=False,
        blank=True,
        related_name="implied_by",
        help_text="Other decorators this one automatically grants"
    )

    conflicts_with = models.ManyToManyField(
        "self",
        symmetrical=True,
        blank=True,
        help_text="Decorators that cannot coexist with this one"
    )

    # Metadata
    is_deprecated = models.BooleanField(
        default=False,
        db_index=True,
        help_text="If true, decorator is deprecated and shouldn't be newly assigned"
    )

    version = models.CharField(
        max_length=20,
        default="1.0",
        help_text="Version for tracking decorator changes"
    )

    sort_order = models.IntegerField(
        default=0,
        help_text="Display order in lists"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "groups_groupdecorator"
        ordering = ["sort_order", "code"]
        verbose_name = "Group Decorator"
        verbose_name_plural = "Group Decorators"
        indexes = [
            models.Index(fields=["category", "is_deprecated"]),
        ]

    def __str__(self):
        return f"{self.code} ({self.category})"

    def is_valid_for_group_type(self, group_type: str) -> bool:
        """Check if this decorator can be applied to a specific group type."""
        if not self.valid_for_types:  # Empty list = valid for all
            return True
        return group_type in self.valid_for_types

    def get_implied_decorators(self):
        """Get all decorators that this one implies (including transitive)."""
        # Simple version - just direct implies
        # Could be enhanced to follow transitive relationships
        return self.implies.filter(is_deprecated=False)

    def conflicts_with_decorator(self, other_code: str) -> bool:
        """Check if this decorator conflicts with another."""
        return self.conflicts_with.filter(code=other_code).exists()


class MembershipDecorator(models.Model):
    """
    Catalog of available membership decorators.
    Defines permissions, identities, and policies for group members.

    Examples:
    - isGroupFounder (identity)
    - can__ManageEvents (permission)
    - can__ModerateComments (permission)
    """

    code = models.SlugField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="Unique code (e.g., 'isGroupFounder', 'can__ManageEvents')"
    )

    category = models.CharField(
        max_length=20,
        choices=DecoratorCategory.choices,
        db_index=True,
        help_text="Category: identity, permission, or policy"
    )

    label = models.CharField(
        max_length=255,
        help_text="Human-readable label"
    )

    description = models.TextField(
        blank=True,
        help_text="Detailed description of what this decorator grants"
    )

    # Decorator relationships
    implies = models.ManyToManyField(
        "self",
        symmetrical=False,
        blank=True,
        related_name="implied_by",
        help_text="Other decorators this one automatically grants"
    )

    conflicts_with = models.ManyToManyField(
        "self",
        symmetrical=True,
        blank=True,
        help_text="Decorators that cannot coexist with this one"
    )

    # Metadata
    is_deprecated = models.BooleanField(
        default=False,
        db_index=True,
        help_text="If true, decorator is deprecated and shouldn't be newly assigned"
    )

    version = models.CharField(
        max_length=20,
        default="1.0",
        help_text="Version for tracking decorator changes"
    )

    sort_order = models.IntegerField(
        default=0,
        help_text="Display order in lists"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "groups_membershipdecorator"
        ordering = ["sort_order", "code"]
        verbose_name = "Membership Decorator"
        verbose_name_plural = "Membership Decorators"
        indexes = [
            models.Index(fields=["category", "is_deprecated"]),
        ]

    def __str__(self):
        return f"{self.code} ({self.category})"

    def get_implied_decorators(self):
        """Get all decorators that this one implies (including transitive)."""
        return self.implies.filter(is_deprecated=False)

    def conflicts_with_decorator(self, other_code: str) -> bool:
        """Check if this decorator conflicts with another."""
        return self.conflicts_with.filter(code=other_code).exists()
