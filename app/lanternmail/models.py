# lanternmail/models.py

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from fundamentals.bases import BaseModel
from fundamentals.mixins import RichBodyMixin
from django.contrib.auth import get_user_model

from groups.models import Group

User = get_user_model()


class LanternmailPost(RichBodyMixin, BaseModel):
    STATUS_DRAFT = "draft"
    STATUS_REVIEW = "review"
    STATUS_READY = "ready"
    STATUS_SENT = "sent"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_REVIEW, "Review"),
        (STATUS_READY, "Ready"),
        (STATUS_SENT, "Sent"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    VALID_TRANSITIONS = {
        STATUS_DRAFT: {STATUS_REVIEW, STATUS_ARCHIVED},
        STATUS_REVIEW: {STATUS_READY, STATUS_DRAFT, STATUS_ARCHIVED},
        STATUS_READY: {STATUS_DRAFT, STATUS_ARCHIVED},
        STATUS_SENT: {STATUS_ARCHIVED},
        STATUS_ARCHIVED: set(),
    }

    AUDIENCE_MEMBERS = "members"
    AUDIENCE_SUBSCRIBERS = "subscribers"
    AUDIENCE_PUBLIC_FOLLOWERS = "public_followers"
    AUDIENCE_CUSTOM = "custom"
    AUDIENCE_CHOICES = [
        (AUDIENCE_MEMBERS, "Members"),
        (AUDIENCE_SUBSCRIBERS, "Subscribers"),
        (AUDIENCE_PUBLIC_FOLLOWERS, "Public Followers"),
        (AUDIENCE_CUSTOM, "Custom"),
    ]

    INGEST_PENDING = "pending"
    INGEST_ELIGIBLE = "eligible"
    INGEST_INGESTED = "ingested"
    INGEST_SKIPPED = "skipped"
    INGEST_CHOICES = [
        (INGEST_PENDING, "Pending"),
        (INGEST_ELIGIBLE, "Eligible"),
        (INGEST_INGESTED, "Ingested"),
        (INGEST_SKIPPED, "Skipped"),
    ]

    group = models.ForeignKey(
        Group, on_delete=models.CASCADE, related_name="lanternmail_posts"
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="lanternmail_posts"
    )
    title = models.CharField(max_length=255)
    subject = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    audience_kind = models.CharField(
        max_length=30, choices=AUDIENCE_CHOICES, default=AUDIENCE_MEMBERS
    )
    mailing_list = models.ForeignKey(
        "lanternmail.LanternmailList",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="posts",
    )
    listmonk_campaign_id = models.IntegerField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    source_content_type = models.ForeignKey(
        ContentType,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    source_object_id = models.PositiveIntegerField(null=True, blank=True)
    source = GenericForeignKey("source_content_type", "source_object_id")
    publication_group = models.ForeignKey(
        "publishing.PublicationGroup",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="lanternmail_posts",
    )
    content_placement = models.ForeignKey(
        "publishing.ContentPlacement",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="lanternmail_posts",
    )
    ingest_status = models.CharField(
        max_length=20, choices=INGEST_CHOICES, default=INGEST_PENDING
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "lanternmail_posts"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.group.title} — {self.title} [{self.status}]"

    def can_transition_to(self, new_status: str) -> bool:
        if new_status == self.status:
            return True
        return new_status in self.VALID_TRANSITIONS.get(self.status, set())

# models.py
class LanternmailList(BaseModel):
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='mailing_lists')  # Changed to ForeignKey for multiple lists
    listmonk_id = models.IntegerField(unique=True)
    listmonk_uuid = models.CharField(max_length=36, unique=True)
    display_name = models.CharField(max_length=100)  # User-entered name
    listmonk_name = models.CharField(max_length=150, unique=True)  # group.slug--display-name
    description = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'lantern_mail_lists'
        unique_together = ['group', 'display_name']  # Prevent duplicate names within a group

    def __str__(self):
        return f"{self.group.title} - {self.display_name}"



# TODO: Future enhancement - Track invitation metadata for analytics and compliance
# Implement this when adding CSV imports and advanced analytics
# See: Hybrid approach for invitation tracking
class LanternmailInvitation(BaseModel):
    # Uncomment and implement when ready for invitation tracking

    mailing_list = models.ForeignKey(LanternmailList, on_delete=models.CASCADE)
    email = models.EmailField()
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    invited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    invitation_source = models.CharField(
        max_length=50,
        choices=[
            ('group_member', 'Group Member'),
            ('external_email', 'External Email'),
            ('csv_import', 'CSV Import'),
        ]
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ('sent', 'Invitation Sent'),
            ('bounced', 'Email Bounced'),
            ('subscribed', 'Subscribed'),
            ('unsubscribed', 'Unsubscribed'),
        ],
        default='sent'
    )
    listmonk_subscriber_id = models.IntegerField(null=True, blank=True)

    class Meta:
        abstract = True  # ✅ This prevents table creation
        unique_together = ['mailing_list', 'email']
        indexes = [
            models.Index(fields=['email', 'status']),
            models.Index(fields=['mailing_list', 'status']),
        ]

    def __str__(self):
        return f"{self.email} → {self.mailing_list.display_name} ({self.status})"


class WelcomeEmailDraft(BaseModel):
    """
    Human-reviewed welcome email created when a prospect converts to a client group.
    Sits in draft until an operator reviews, edits, and sends it manually.
    Listmonk send_tx integration is a future step.
    """
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("sent", "Sent"),
    ]

    prospect = models.ForeignKey(
        "prospects.BusinessProspect",
        on_delete=models.CASCADE,
        related_name="welcome_drafts",
    )
    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name="welcome_drafts",
    )
    to_name = models.CharField(max_length=200)
    to_email = models.EmailField()
    subject = models.CharField(max_length=300)
    body = models.TextField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="draft")
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Welcome Email Draft"

    def __str__(self):
        return f"Welcome → {self.to_email} [{self.status}]"
