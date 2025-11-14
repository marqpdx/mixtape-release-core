# /groups/models.py

from time import timezone
from django.conf import settings
import uuid
from django.contrib.auth import get_user_model
from django.db import models
from django.utils.crypto import get_random_string
from django.utils.text import slugify
from django.utils.timezone import now
from django.utils.crypto import get_random_string
from django.contrib.postgres.fields import ArrayField

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from fundamentals.bases import BaseModel
from fundamentals.models import BaseContent, LayoutParent
from groups.models.dec_enums import GroupType, GroupVisibility

def generate_token():
    return get_random_string(64)

User = get_user_model()


class Group(LayoutParent, BaseContent):
    id = models.UUIDField(primary_key=True, editable=False, unique=True, default=uuid.uuid4)
    description = models.TextField(blank=True)
    group_type = models.CharField(max_length=20, choices=GroupType.choices)

    profile_image = models.CharField(max_length=500, blank=True, null=True)
    profile_image_path = models.CharField(max_length=512, blank=True, null=True)
    background_image = models.CharField(max_length=500, blank=True, null=True)
    background_image_path = models.CharField(max_length=512, blank=True, null=True)

    # ============================================================================
    # PHASE 3: Identity Integration (Deferred)
    # ============================================================================
    # emblem = models.ForeignKey(
    #     "identity.EmblemAvatar",
    #     null=True, blank=True,
    #     on_delete=models.SET_NULL,
    #     related_name="groups",
    # )

    is_active = models.BooleanField(default=True, db_index=True)

    visibility = models.CharField(
        max_length=20,
        choices=GroupVisibility.choices,
        default=GroupVisibility.PUBLIC,
    )

    def is_member(self, user):
        """
        Check if user is a member of this group.
        Works with GenericForeignKey membership model.
        """
        if not user.is_authenticated:
            return False

        from django.contrib.contenttypes.models import ContentType
        user_content_type = ContentType.objects.get_for_model(user)

        return self.memberships.filter(
            member_content_type=user_content_type,
            member_object_id=user.id,
            is_active=True,
            is_banned=False,
            is_evicted=False,
            is_pending=False
        ).exists()

    def can_user_view_drafts(self, user):

        return True
        # TODO  make this real.


        """
        Check if user can view drafts in this group.
        Implement your permission logic here.
        """
        if not user.is_authenticated:
            return False

        # Example permission logic - adjust based on your needs:
        # - Group members can view drafts
        # - Public groups allow any authenticated user

        if self.is_member(user):
            return True

        # If it's a public group, allow any authenticated user
        if getattr(self, 'visibility', None) == 'public':
            return True

        return False

    def can_user_view_content(self, user):
        """
        Check if user can view content in this group.
        Implement your permission logic here.
        """

        return True

        # TODO make this real.

        if not user.is_authenticated:
            return False

        # Example permission logic - adjust based on your needs:
        # - Group members can view content
        # - Public groups allow any authenticated user

        if self.is_member(user):
            return True

        # If it's a public group, allow any authenticated user
        if getattr(self, 'visibility', None) == 'public':
            return True

        return False


# INVITATION MODELS

class EmailStatus(models.TextChoices):
    SENDING = "sending", "Sending invitation"
    SENT = "sent", "Invitation email sent"
    FAILED = "failed", "Failed to send invitation"


class InvitationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    JOINED = "joined", "Joined"
    DECLINED = "declined", "Declined"
    EXPIRED = "expired", "Expired"


class GroupInvitation(BaseModel):
    invited_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="invitations_sent"
    )
    invited_user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invitations_received"
    )
    invited_email = models.EmailField()

    group = models.ForeignKey("groups.Group", on_delete=models.CASCADE, related_name="invitations")

    message = models.TextField(blank=True)

    token = models.CharField(max_length=64, unique=True, default=generate_token)

    email_status = models.CharField(
        max_length=20,
        choices=EmailStatus.choices,
        default=EmailStatus.SENDING,
    )
    invitation_status = models.CharField(
        max_length=20,
        choices=InvitationStatus.choices,
        default=InvitationStatus.PENDING,
    )

    expires_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        constraints = []

    def is_expired(self):
        return self.expires_at and self.expires_at < now()

    def __str__(self):
        return f"Invite to {self.group} for {self.invited_email}"


class InviteLink(models.Model):
    shortcode = models.CharField(max_length=20, unique=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    token = models.TextField()
    is_used = models.BooleanField(default=False)
    invited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="sent_invites")
    created_at = models.DateTimeField(auto_now_add=True)



# NOTICEBOARD MODELS


class GroupAnnouncement(models.Model):
    """
    Group-wide announcements shown on the noticeboard.
    Admin-curated, single source (no fan-out to users).
    Supports auto-creation from content (courses, events, posts).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.ForeignKey('groups.Group', on_delete=models.CASCADE, related_name='announcements')

    # ---- CONTENT ----
    title = models.CharField(max_length=200)
    content = models.TextField(help_text="Main announcement message")

    # ---- PRIORITY & ORDERING ----
    priority = models.CharField(
        max_length=16,
        default='normal',
        choices=[
            ('critical', 'Critical'),
            ('high', 'High'),
            ('normal', 'Normal'),
        ],
        help_text="Determines display order in the queue"
    )
    position = models.IntegerField(
        default=0,
        help_text="Admin can manually reorder. Lower numbers appear first."
    )

    # ---- LIFECYCLE ----
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Auto-hide after this datetime"
    )

    # ---- AUTHORSHIP ----
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_announcements'
    )

    # ---- SOURCE CONTENT (Polymorphic) ----
    # If announcement was auto-created from a course, event, post, etc.
    source_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='announcements'
    )
    source_object_id = models.UUIDField(null=True, blank=True)
    source = GenericForeignKey("source_content_type", "source_object_id")

    # ---- CALL TO ACTION ----
    cta_text = models.CharField(
        max_length=100,
        blank=True,
        help_text="Button text like 'View Course', 'RSVP', 'Read More'"
    )
    cta_url = models.CharField(
        max_length=500,
        blank=True,
        help_text="Link to the content"
    )

    # ---- NOTIFICATION INTEGRATION (Optional) ----
    also_send_notification = models.BooleanField(
        default=False,
        help_text="If True, also creates Notifications for all group members (use sparingly!)"
    )
    notification_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['priority', 'position', '-created_at']
        indexes = [
            models.Index(fields=['group', 'is_active', 'expires_at']),
            models.Index(fields=['group', 'priority', 'position']),
            models.Index(fields=['source_content_type', 'source_object_id']),
        ]

    def __str__(self):
        return f"{self.group.title}: {self.title}"

    @property
    def is_expired(self):
        """Check if announcement has passed its expiration date"""
        if self.expires_at is None:
            return False
        return timezone.now() > self.expires_at

    @property
    def priority_value(self):
        """Numeric value for priority sorting"""
        return {'critical': 0, 'high': 1, 'normal': 2}.get(self.priority, 2)

    def get_visible_for_user(self, user):
        """
        Check if this announcement should be visible to the user.
        Considers: active status, expiration, and user dismissals.
        """
        if not self.is_active or self.is_expired:
            return False

        # Check dismissals
        dismissal = self.dismissals.filter(user=user).first()
        if dismissal:
            if dismissal.dismissal_type == 'permanent':
                return False
            if dismissal.dismissal_type == 'snooze' and dismissal.snoozed_until:
                if timezone.now() < dismissal.snoozed_until:
                    return False

        return True

    @classmethod
    def get_visible_queue_for_user(cls, group, user):
        """
        Get the queue of announcements visible to this user,
        sorted by priority and position.
        """
        announcements = cls.objects.filter(
            group=group,
            is_active=True
        ).select_related('author')

        # Filter out expired and dismissed
        visible = [a for a in announcements if a.get_visible_for_user(user)]

        # Sort by priority (critical first), then position, then created_at
        return sorted(
            visible,
            key=lambda a: (a.priority_value, a.position, -a.created_at.timestamp())
        )


class AnnouncementDismissal(models.Model):
    """
    Tracks user dismissals of announcements.
    First dismiss = 48hr snooze, second dismiss = permanent.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    announcement = models.ForeignKey(
        GroupAnnouncement,
        on_delete=models.CASCADE,
        related_name='dismissals'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='announcement_dismissals'
    )

    # ---- DISMISSAL TYPE ----
    dismissal_type = models.CharField(
        max_length=16,
        choices=[
            ('snooze', 'Snoozed for 48 hours'),
            ('permanent', 'Permanently dismissed'),
        ]
    )

    dismissed_at = models.DateTimeField(auto_now_add=True)
    snoozed_until = models.DateTimeField(
        null=True,
        blank=True,
        help_text="For snooze type, when to show again"
    )

    class Meta:
        unique_together = ('announcement', 'user')
        indexes = [
            models.Index(fields=['user', 'dismissal_type']),
            models.Index(fields=['snoozed_until']),
        ]

    def __str__(self):
        return f"{self.user.username} dismissed {self.announcement.title} ({self.dismissal_type})"

    @classmethod
    def dismiss_announcement(cls, announcement, user):
        """
        Handle dismissal logic:
        - First time: 48hr snooze
        - Second time: permanent
        """
        existing = cls.objects.filter(
            announcement=announcement,
            user=user
        ).first()

        if not existing:
            # First dismiss = snooze for 48 hours
            snooze_until = timezone.now() + timezone.timedelta(hours=48)
            dismissal = cls.objects.create(
                announcement=announcement,
                user=user,
                dismissal_type='snooze',
                snoozed_until=snooze_until
            )
            return 'snooze', snooze_until

        elif existing.dismissal_type == 'snooze':
            # Second dismiss = permanent
            existing.dismissal_type = 'permanent'
            existing.snoozed_until = None
            existing.dismissed_at = timezone.now()
            existing.save()
            return 'permanent', None

        # Already permanently dismissed
        return 'permanent', None