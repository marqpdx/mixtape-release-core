# groups/models/public_page.py

from django.db import models
from django.utils import timezone


class PublicPage(models.Model):
    """
    A group's public organizational presence page on Crossroads.

    One page per group (OneToOne). The lifecycle moves draft → pending_approval
    → published → archived. No transition to published is automatic; every
    state change is admin-initiated.

    draft_content holds the working snapshot (slots populated from Group DB
    fields). published_content holds the last approved snapshot. The existing
    published version stays live until a new version clears pending_approval.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING_APPROVAL = "pending_approval", "Pending Approval"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    class LayoutTemplate(models.TextChoices):
        STANDARD = "standard", "Standard"
        HERO = "hero", "Hero"
        FOCUS = "focus", "Focus"
        DIRECTORY = "directory", "Directory"

    group = models.OneToOneField(
        "groups.Group",
        on_delete=models.PROTECT,
        related_name="public_page",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    draft_content = models.JSONField(
        default=dict,
        help_text="Current draft slot values — not yet published.",
    )
    published_content = models.JSONField(
        null=True,
        blank=True,
        help_text="Content snapshot as of last approval; served to anonymous readers.",
    )
    layout_template = models.CharField(
        max_length=20,
        choices=LayoutTemplate.choices,
        default=LayoutTemplate.STANDARD,
    )
    needs_review = models.BooleanField(
        default=False,
        help_text="Steward-flagged: this page needs attention. Does not remove it from public view.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "groups"

    def __str__(self):
        return f"PublicPage({self.group.slug}, {self.status})"

    def submit_for_approval(self):
        """Move draft to pending_approval."""
        if self.status not in (self.Status.DRAFT,):
            raise ValueError(f"Cannot submit from status '{self.status}'.")
        self.status = self.Status.PENDING_APPROVAL
        self.save(update_fields=["status", "updated_at"])

    def publish(self):
        """Approve and publish — copies draft_content to published_content."""
        self.published_content = self.draft_content
        self.status = self.Status.PUBLISHED
        self.published_at = timezone.now()
        self.save(update_fields=["status", "published_content", "published_at", "updated_at"])

    def revert_to_draft(self):
        """Move pending_approval back to draft (e.g. rejected)."""
        if self.status != self.Status.PENDING_APPROVAL:
            raise ValueError(f"Cannot revert from status '{self.status}'.")
        self.status = self.Status.DRAFT
        self.save(update_fields=["status", "updated_at"])

    def unpublish(self):
        """Take a published page offline — returns to draft for re-editing."""
        if self.status != self.Status.PUBLISHED:
            raise ValueError(f"Cannot unpublish from status '{self.status}'.")
        self.status = self.Status.DRAFT
        self.published_at = None
        self.save(update_fields=["status", "published_at", "updated_at"])

    def archive(self):
        """Permanently retire a published page."""
        if self.status != self.Status.PUBLISHED:
            raise ValueError(f"Cannot archive from status '{self.status}'.")
        self.status = self.Status.ARCHIVED
        self.save(update_fields=["status", "updated_at"])
