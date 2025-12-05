# groups/models/decorators/profiles.py
"""
Decorator profile models.
Profiles bundle decorators together for easy application to groups/memberships.
"""

from django.contrib.postgres.fields import ArrayField
from django.db import models

from .catalog import GroupDecorator, MembershipDecorator


class GroupDecoratorProfile(models.Model):
    """
    Bundles of group decorators for easy application.

    Examples:
    - profile__Band → [isA__Band, can__HostEvents, can__HaveGallery]
    - profile__PTA → [isA__PTA, can__EnableApplications, policy__ModeratedForums]
    """

    code = models.SlugField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="Unique profile code (e.g., 'profile__Band')"
    )

    label = models.CharField(
        max_length=255,
        help_text="Human-readable label"
    )

    description = models.TextField(
        blank=True,
        help_text="What this profile represents"
    )

    valid_for_types = ArrayField(
        models.CharField(max_length=20),
        default=list,
        blank=True,
        help_text="Group types this profile can be applied to (empty = all types)"
    )

    decorators = models.ManyToManyField(
        GroupDecorator,
        through="GroupProfileItem",
        related_name="profiles",
        help_text="Decorators included in this profile"
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="If false, profile cannot be applied to new groups"
    )

    sort_order = models.IntegerField(
        default=0,
        help_text="Display order in lists"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "groups_groupdecoratorprofile"
        ordering = ["sort_order", "code"]
        verbose_name = "Group Decorator Profile"
        verbose_name_plural = "Group Decorator Profiles"

    def __str__(self):
        return self.label

    def is_valid_for_group_type(self, group_type: str) -> bool:
        """Check if this profile can be applied to a specific group type."""
        if not self.valid_for_types:  # Empty list = valid for all
            return True
        return group_type in self.valid_for_types


class GroupProfileItem(models.Model):
    """
    Through model linking GroupDecoratorProfile to GroupDecorator.
    Allows ordering and optional configuration per decorator.
    """

    profile = models.ForeignKey(
        GroupDecoratorProfile,
        on_delete=models.CASCADE,
        related_name="items"
    )

    decorator = models.ForeignKey(
        GroupDecorator,
        on_delete=models.CASCADE,
        related_name="profile_items"
    )

    sort_order = models.IntegerField(
        default=0,
        help_text="Order within the profile"
    )

    is_required = models.BooleanField(
        default=True,
        help_text="If false, this decorator is optional when applying the profile"
    )

    class Meta:
        db_table = "groups_groupprofileitem"
        ordering = ["sort_order"]
        unique_together = [("profile", "decorator")]

    def __str__(self):
        return f"{self.profile.code} → {self.decorator.code}"


class MembershipDecoratorProfile(models.Model):
    """
    Bundles of membership decorators for easy application.

    Examples:
    - profile__Archivist → [can__EditPosts, can__ManageThreadworks]
    - profile__Treasurer → [can__ViewFinancials, can__ProcessDonations]
    """

    code = models.SlugField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="Unique profile code (e.g., 'profile__Archivist')"
    )

    label = models.CharField(
        max_length=255,
        help_text="Human-readable label"
    )

    description = models.TextField(
        blank=True,
        help_text="What this profile represents"
    )

    decorators = models.ManyToManyField(
        MembershipDecorator,
        through="MembershipProfileItem",
        related_name="profiles",
        help_text="Decorators included in this profile"
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="If false, profile cannot be applied to new memberships"
    )

    sort_order = models.IntegerField(
        default=0,
        help_text="Display order in lists"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "groups_membershipdecoratorprofile"
        ordering = ["sort_order", "code"]
        verbose_name = "Membership Decorator Profile"
        verbose_name_plural = "Membership Decorator Profiles"

    def __str__(self):
        return self.label


class MembershipProfileItem(models.Model):
    """
    Through model linking MembershipDecoratorProfile to MembershipDecorator.
    Allows ordering and optional configuration per decorator.
    """

    profile = models.ForeignKey(
        MembershipDecoratorProfile,
        on_delete=models.CASCADE,
        related_name="items"
    )

    decorator = models.ForeignKey(
        MembershipDecorator,
        on_delete=models.CASCADE,
        related_name="profile_items"
    )

    sort_order = models.IntegerField(
        default=0,
        help_text="Order within the profile"
    )

    is_required = models.BooleanField(
        default=True,
        help_text="If false, this decorator is optional when applying the profile"
    )

    class Meta:
        db_table = "groups_membershipprofileitem"
        ordering = ["sort_order"]
        unique_together = [("profile", "decorator")]

    def __str__(self):
        return f"{self.profile.code} → {self.decorator.code}"
