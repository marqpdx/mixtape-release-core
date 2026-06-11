# threadworks/models.py

from django.db import models
from django.utils.text import slugify
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.db.models import Q, Count, Max
from django.utils import timezone

from fundamentals.models import BaseContent, BaseModel, BaseData

CustomUser = get_user_model()

class Forum(BaseContent):
    """
    Forum container with polymorphic sponsor (User, Group, etc).
    Inherits slug lifecycle, title, summary from BaseContent/BaseData.
    """
    VISIBILITY_CHOICES = [
        ("public", "Public"),
        ("members", "Members"),
        ("group", "Group Only")
    ]

    AUDIENCE_CHOICES = [
        ("all_members", "All Group Members"),
        ("subset", "Specific Members"),
    ]

    description = models.TextField(blank=True)
    visibility = models.CharField(
        max_length=10,
        choices=VISIBILITY_CHOICES,
        default="group"
    )
    is_archived = models.BooleanField(default=False)

    audience_type = models.CharField(
        max_length=20,
        choices=AUDIENCE_CHOICES,
        default="all_members",
    )
    auto_add_new_members = models.BooleanField(
        default=True,
        help_text="When audience is All Group Members, automatically include new group members.",
    )
    audience_members = models.ManyToManyField(
        CustomUser,
        related_name="subset_forums",
        blank=True,
        help_text="Explicit member list used when audience_type='subset'.",
    )

    class Meta:
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['visibility', '-updated_at']),
            models.Index(fields=['sponsor_content_type', 'sponsor_object_id', '-updated_at']),
        ]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('threadworks:forum_detail', kwargs={'slug': self.slug})

    @property
    def discussion_count(self):
        """Count of non-deleted discussions"""
        return self.discussions.filter(is_deleted=False).count()

    @property
    def recent_participants(self):
        """Get users who posted in last 30 days, ordered by recency"""
        from datetime import timedelta
        cutoff = timezone.now() - timedelta(days=30)
        return CustomUser.objects.filter(
            posts__discussion__forum=self,
            posts__created_at__gte=cutoff,
            posts__is_deleted=False
        ).distinct().order_by('-posts__created_at')[:10]

    @property
    def last_activity(self):
        """Get timestamp of most recent post in this forum"""
        latest_post = self.discussions.filter(
            is_deleted=False,
            posts__is_deleted=False
        ).aggregate(Max('posts__created_at'))['posts__created_at__max']
        return latest_post


class Discussion(BaseData):
    """
    Threaded discussion with title, owned by a forum.
    Inherits title, slug, slug_is_custom, slug_history from BaseData.
    Inherits created_at, updated_at from BaseModel (via BaseData).
    """
    forum = models.ForeignKey(
        Forum,
        on_delete=models.CASCADE,
        related_name="discussions"
    )
    description = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        related_name="discussions"
    )

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('archived', 'Archived'),
        ('pinned', 'Pinned'),
    ]
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='active'
    )

    pinned_nav_name = models.CharField(
        max_length=32,
        blank=True,
        default='',
        help_text="Short label used in group nav when this discussion is pinned. Ignored unless status='pinned'.",
    )

    is_locked = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']
        unique_together = ['forum', 'slug']
        indexes = [
            models.Index(fields=['forum', '-created_at']),
            models.Index(fields=['created_by', '-created_at']),
            models.Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return self.title

    def slug_exists(self, slug: str) -> bool:
        """
        Override to check uniqueness scoped to forum.
        (forum, slug) must be unique.
        """
        return Discussion.objects.filter(
            forum=self.forum,
            slug=slug
        ).exclude(pk=self.pk).exists()

    def get_absolute_url(self):
        return reverse('threadworks:discussion_detail', kwargs={
            'forum_slug': self.forum.slug,
            'discussion_slug': self.slug
        })

    @property
    def post_count(self):
        """Count of non-deleted posts"""
        return self.posts.filter(is_deleted=False).count()

    @property
    def last_post(self):
        """Most recent non-deleted post"""
        return self.posts.filter(is_deleted=False).order_by('-created_at').first()

    @property
    def participants(self):
        """All users who have posted in this discussion"""
        return CustomUser.objects.filter(
            posts__discussion=self,
            posts__is_deleted=False
        ).distinct()


class Post(BaseModel):
    """
    Single contribution to a discussion.
    Inherits created_at, updated_at from BaseModel.
    """
    discussion = models.ForeignKey(
        Discussion,
        on_delete=models.CASCADE,
        related_name="posts"
    )
    author = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        related_name="posts"
    )
    content = models.TextField()
    is_deleted = models.BooleanField(default=False)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="replies"
    )

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['discussion', 'created_at']),
            models.Index(fields=['author', '-created_at']),
            models.Index(fields=['parent', 'created_at']),
        ]

    def __str__(self):
        return f"Post by {self.author.username if self.author else 'Unknown'} in {self.discussion.title}"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)

        # Update discussion's updated_at via signal or just touch it
        if is_new:
            self.discussion.save(update_fields=['updated_at'])

    @property
    def is_edited(self):
        """Check if post has been edited (updated_at differs significantly from created_at)"""
        if not self.updated_at:
            return False
        # Consider edited if updated more than 1 minute after creation
        return (self.updated_at - self.created_at).total_seconds() > 60


class PostReaction(BaseModel):
    """User reactions to posts"""
    REACTION_CHOICES = [
        ('like', '👍'),
        ('heart', '❤️'),
        ('laugh', '😂'),
        ('wow', '😮'),
        ('sad', '😢'),
        ('angry', '😠'),
    ]

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="reactions")
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    reaction = models.CharField(max_length=10, choices=REACTION_CHOICES)

    class Meta:
        unique_together = ['post', 'user', 'reaction']
        indexes = [
            models.Index(fields=['post', 'reaction']),
        ]


class PostFlag(BaseModel):
    """Moderation: flag problematic posts"""
    REASON_CHOICES = [
        ('spam', 'Spam'),
        ('inappropriate', 'Inappropriate Content'),
        ('harassment', 'Harassment'),
        ('misinformation', 'Misinformation'),
        ('other', 'Other'),
    ]

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="flags")
    user = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    reason = models.CharField(max_length=20, choices=REASON_CHOICES)
    description = models.TextField(blank=True)
    is_resolved = models.BooleanField(default=False)
    resolved_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_flags"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ['post', 'user']
        indexes = [
            models.Index(fields=['is_resolved', '-created_at']),
        ]


class ForumMembership(BaseModel):
    """Explicit forum membership (for permissions/roles)"""
    ROLE_CHOICES = [
        ('member', 'Member'),
        ('moderator', 'Moderator'),
        ('admin', 'Admin'),
    ]

    forum = models.ForeignKey(Forum, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="forum_memberships")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='member')
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ['forum', 'user']
        indexes = [
            models.Index(fields=['forum', 'role']),
            models.Index(fields=['user', '-created_at']),
        ]


class DiscussionView(BaseModel):
    """Track when users last viewed discussions (for "new posts since" feature)"""
    discussion = models.ForeignKey(Discussion, on_delete=models.CASCADE, related_name="views")
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="discussion_views")
    last_post_seen = models.ForeignKey(
        Post,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="view_markers"
    )

    class Meta:
        unique_together = ['discussion', 'user']
        indexes = [
            models.Index(fields=['user', '-updated_at']),
            models.Index(fields=['discussion', '-updated_at']),
        ]


class ForumNotification(BaseModel):
    """Forum-wide and discussion-level notifications"""
    NOTIFICATION_TYPES = [
        ('new_post', 'New Post'),
        ('mention', 'Mention'),
        ('reply', 'Reply to Your Post'),
        ('discussion_locked', 'Discussion Locked'),
        ('discussion_pinned', 'Discussion Pinned'),
    ]

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="forum_notifications")
    forum = models.ForeignKey(Forum, on_delete=models.CASCADE)
    discussion = models.ForeignKey(Discussion, on_delete=models.CASCADE, null=True, blank=True)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, null=True, blank=True)
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read', '-created_at']),
            models.Index(fields=['forum', '-created_at']),
        ]




