# groups/models/types.py
"""
Type-specific models for the four group types.
Each extends the base Group model via OneToOne relationship.
"""

from django.conf import settings
from django.db import models

from .dec_enums import AdmissionPolicy, GovernanceModel, MeetingFrequency, PrivacyLevel


class PersonaGroup(models.Model):
    """
    Personal container group, optionally 1:1 with a User.
    Used for personal spaces, portfolios, or individual identity.
    """

    group = models.OneToOneField(
        "Group",
        on_delete=models.CASCADE,
        related_name="persona_detail",
        primary_key=True
    )

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="persona_group",
        null=True,
        blank=True,
        help_text="User this persona belongs to (if 1:1 mapping)"
    )

    privacy_level = models.CharField(
        max_length=20,
        choices=PrivacyLevel.choices,
        default=PrivacyLevel.PUBLIC,
        help_text="Who can view this persona's content"
    )

    display_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Display name (can differ from group title)"
    )

    auto_created_home_circle = models.ForeignKey(
        "Group",
        on_delete=models.SET_NULL,
        related_name="persona_homes",
        null=True,
        blank=True,
        help_text="Auto-created home circle for this persona"
    )

    class Meta:
        db_table = "groups_personagroup"
        verbose_name = "Persona Group"
        verbose_name_plural = "Persona Groups"

    def __str__(self):
        return f"Persona: {self.group.title}"


class CircleGroup(models.Model):
    """
    Atomic working unit/team.
    Circles are the smallest collaborative unit - they cannot contain other groups.
    """

    group = models.OneToOneField(
        "Group",
        on_delete=models.CASCADE,
        related_name="circle_detail",
        primary_key=True
    )

    start_date = models.DateField(
        null=True,
        blank=True,
        help_text="When this circle started"
    )

    end_date = models.DateField(
        null=True,
        blank=True,
        help_text="When this circle ends (if time-bound)"
    )

    capacity = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Maximum number of members (optional)"
    )

    meeting_frequency = models.CharField(
        max_length=20,
        choices=MeetingFrequency.choices,
        default=MeetingFrequency.WEEKLY,
        blank=True,
        help_text="How often the circle meets"
    )

    is_time_bound = models.BooleanField(
        default=False,
        help_text="Is this a project circle (time-bound) or ongoing?"
    )

    class Meta:
        db_table = "groups_circlegroup"
        verbose_name = "Circle Group"
        verbose_name_plural = "Circle Groups"

    def __str__(self):
        return f"Circle: {self.group.title}"

    @property
    def is_active_timebound(self):
        """Check if a time-bound circle is currently active."""
        if not self.is_time_bound:
            return True

        from django.utils import timezone
        now = timezone.now().date()

        if self.start_date and now < self.start_date:
            return False
        if self.end_date and now > self.end_date:
            return False

        return True


class CommunityGroup(models.Model):
    """
    Larger collective containing Circles.
    Communities are the primary organizational structure in Mixtape.
    """

    group = models.OneToOneField(
        "Group",
        on_delete=models.CASCADE,
        related_name="community_detail",
        primary_key=True
    )

    admission_policy = models.CharField(
        max_length=20,
        choices=AdmissionPolicy.choices,
        default=AdmissionPolicy.OPEN,
        help_text="How new members can join"
    )

    tagline = models.CharField(
        max_length=255,
        blank=True,
        help_text="Short tagline for the community"
    )

    location = models.CharField(
        max_length=255,
        blank=True,
        help_text="Geographic location (city, region, etc.)"
    )

    class Meta:
        db_table = "groups_communitygroup"
        verbose_name = "Community Group"
        verbose_name_plural = "Community Groups"

    def __str__(self):
        return f"Community: {self.group.title}"


class CoalitionGroup(models.Model):
    """
    Federation of groups (can contain any group type).
    Coalitions enable cross-group collaboration and shared governance.
    """

    group = models.OneToOneField(
        "Group",
        on_delete=models.CASCADE,
        related_name="coalition_detail",
        primary_key=True
    )

    governance_model = models.CharField(
        max_length=20,
        choices=GovernanceModel.choices,
        default=GovernanceModel.CONSENSUS,
        help_text="How decisions are made in this coalition"
    )

    charter = models.TextField(
        blank=True,
        help_text="Coalition charter or founding document"
    )

    allow_cross_posting = models.BooleanField(
        default=True,
        help_text="Allow posts to be shared across member groups"
    )

    shared_resources = models.BooleanField(
        default=False,
        help_text="Enable shared resource pools across groups"
    )

    class Meta:
        db_table = "groups_coalitiongroup"
        verbose_name = "Coalition Group"
        verbose_name_plural = "Coalition Groups"

    def __str__(self):
        return f"Coalition: {self.group.title}"
