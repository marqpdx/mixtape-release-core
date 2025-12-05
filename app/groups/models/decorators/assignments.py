# groups/models/decorators/assignments.py
"""
Decorator assignment models.
Link decorators to specific groups and memberships.
"""

from django.conf import settings
from django.db import models

from ..dec_enums import AssignmentSource
from .catalog import GroupDecorator, MembershipDecorator
from .profiles import GroupDecoratorProfile, MembershipDecoratorProfile


class GroupHasDecorator(models.Model):
    """
    Links a decorator to a specific group.
    Tracks how and why the decorator was assigned.
    """

    group = models.ForeignKey(
        "groups.Group",
        on_delete=models.CASCADE,
        related_name="decorator_links"
    )

    decorator = models.ForeignKey(
        GroupDecorator,
        on_delete=models.CASCADE,
        related_name="group_links"
    )

    enabled = models.BooleanField(
        default=True,
        db_index=True,
        help_text="If false, decorator is present but disabled"
    )

    source = models.CharField(
        max_length=20,
        choices=AssignmentSource.choices,
        default=AssignmentSource.MANUAL,
        help_text="How this decorator was assigned"
    )

    source_profile = models.ForeignKey(
        GroupDecoratorProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assignments",
        help_text="Profile that assigned this decorator (if source=profile)"
    )

    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="group_decorators_assigned"
    )

    reason = models.TextField(
        blank=True,
        help_text="Optional reason for assignment"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Optional expiration date for temporary decorators"
    )

    class Meta:
        db_table = "groups_grouphasdecorator"
        unique_together = [("group", "decorator")]
        ordering = ["group", "decorator"]
        verbose_name = "Group Has Decorator"
        verbose_name_plural = "Groups Have Decorators"
        indexes = [
            models.Index(fields=["group", "enabled"]),
            models.Index(fields=["decorator", "enabled"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self):
        status = "enabled" if self.enabled else "disabled"
        return f"{self.group.title} → {self.decorator.code} ({status})"

    @property
    def is_expired(self):
        """Check if this decorator assignment has expired."""
        if not self.expires_at:
            return False

        from django.utils import timezone
        return timezone.now() > self.expires_at

    def is_active(self):
        """Check if this decorator is currently active (enabled and not expired)."""
        return self.enabled and not self.is_expired


class MembershipHasDecorator(models.Model):
    """
    Links a decorator to a specific membership.
    Tracks permissions and capabilities granted to group members.
    """

    membership = models.ForeignKey(
        "groups.GroupMembership",
        on_delete=models.CASCADE,
        related_name="decorator_links"
    )

    decorator = models.ForeignKey(
        MembershipDecorator,
        on_delete=models.CASCADE,
        related_name="membership_links"
    )

    enabled = models.BooleanField(
        default=True,
        db_index=True,
        help_text="If false, decorator is present but disabled"
    )

    source = models.CharField(
        max_length=20,
        choices=AssignmentSource.choices,
        default=AssignmentSource.MANUAL,
        help_text="How this decorator was assigned"
    )

    source_profile = models.ForeignKey(
        MembershipDecoratorProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assignments",
        help_text="Profile that assigned this decorator (if source=profile)"
    )

    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="membership_decorators_assigned"
    )

    reason = models.TextField(
        blank=True,
        help_text="Optional reason for assignment"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Optional expiration date for temporary decorators"
    )

    class Meta:
        db_table = "groups_membershiphasdecorator"
        unique_together = [("membership", "decorator")]
        ordering = ["membership", "decorator"]
        verbose_name = "Membership Has Decorator"
        verbose_name_plural = "Memberships Have Decorators"
        indexes = [
            models.Index(fields=["membership", "enabled"]),
            models.Index(fields=["decorator", "enabled"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self):
        status = "enabled" if self.enabled else "disabled"
        return f"{self.membership} → {self.decorator.code} ({status})"

    @property
    def is_expired(self):
        """Check if this decorator assignment has expired."""
        if not self.expires_at:
            return False

        from django.utils import timezone
        return timezone.now() > self.expires_at

    def is_active(self):
        """Check if this decorator is currently active (enabled and not expired)."""
        return self.enabled and not self.is_expired
