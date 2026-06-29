# threadworks/models.py

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Max, Q
from django.utils.text import slugify
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from fundamentals.models import BaseContent, BaseModel, BaseData

CustomUser = get_user_model()

_VISIBILITY_SCOPE_CHOICES = [
    ('circle', 'Circle Only'),
    ('group', 'Group'),
    ('crossroads', 'Crossroads'),
]

_CREATION_SIGNAL_CHOICES = [
    ('low', 'Low'),
    ('medium', 'Medium'),
    ('high', 'High'),
]


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
    is_contained_circle = models.BooleanField(
        default=False,
        help_text="When True, visibility is Circle-only; one-level-up sharing is not offered (D15).",
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
        return self.discussions.filter(is_deleted=False).count()

    @property
    def recent_participants(self):
        from datetime import timedelta
        cutoff = timezone.now() - timedelta(days=30)
        return CustomUser.objects.filter(
            Q(
                posts__discussion__forum=self,
                posts__created_at__gte=cutoff,
                posts__is_deleted=False,
            ) | Q(
                posts__feed_post__forum=self,
                posts__created_at__gte=cutoff,
                posts__is_deleted=False,
            )
        ).distinct().order_by('-posts__created_at')[:10]

    @property
    def last_activity(self):
        discussion_latest = self.discussions.filter(
            is_deleted=False,
            posts__is_deleted=False,
        ).aggregate(ts=Max('posts__created_at'))['ts']
        feedpost_latest = self.feed_posts.filter(
            is_deleted=False,
            posts__is_deleted=False,
        ).aggregate(ts=Max('posts__created_at'))['ts']
        if discussion_latest and feedpost_latest:
            return max(discussion_latest, feedpost_latest)
        return discussion_latest or feedpost_latest


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

    # D14 — visibility scope
    visibility_scope = models.CharField(
        max_length=12,
        choices=_VISIBILITY_SCOPE_CHOICES,
        default='group',
    )

    # D6 — memory-value score (continuous; updated by signal events)
    memory_value_score = models.FloatField(default=0.0)

    # D8 — timeliness modifier (accelerates decay after this date)
    timeliness_date = models.DateField(null=True, blank=True)

    # D9 — creation-time signal (optional; seeds memory-value score)
    creation_signal = models.CharField(
        max_length=6,
        choices=_CREATION_SIGNAL_CHOICES,
        null=True,
        blank=True,
    )

    # D12 — Beryl-generated, moderator-mediated summary
    summary = models.TextField(null=True, blank=True)
    summary_pending = models.TextField(null=True, blank=True)
    summary_pending_delta = models.FloatField(
        null=True,
        blank=True,
        help_text="Percentage of summary text changed vs. approved summary (0.0–1.0).",
    )
    summary_pending_substantive = models.BooleanField(
        null=True,
        blank=True,
        help_text="Heuristic flag: True when candidate contains substantive changes beyond the delta.",
    )

    # D13 — resolution state (reserved; no UI in Phase 1)
    resolution_post = models.ForeignKey(
        'Post',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )

    class Meta:
        ordering = ['-created_at']
        unique_together = ['forum', 'slug']
        indexes = [
            models.Index(fields=['forum', '-created_at']),
            models.Index(fields=['created_by', '-created_at']),
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['forum', '-memory_value_score']),
            models.Index(fields=['-updated_at'], name='discussion_updated_at_desc'),
        ]

    def __str__(self):
        return self.title

    def slug_exists(self, slug: str) -> bool:
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
        return self.posts.filter(is_deleted=False).count()

    @property
    def last_post(self):
        return self.posts.filter(is_deleted=False).order_by('-created_at').first()

    @property
    def participants(self):
        return CustomUser.objects.filter(
            posts__discussion=self,
            posts__is_deleted=False
        ).distinct()


class FeedPost(BaseModel):
    """
    Artifact-centric content type; sibling to Discussion within a Forum (D4).
    Media-rich: text / image / link / voice; borrows composition patterns from
    Storyline Leaf (confirmed by spike, 2026-06-20).
    """
    KIND_TEXT = 'text'
    KIND_IMAGE = 'image'
    KIND_LINK = 'link'
    KIND_VOICE = 'voice'
    KIND_CHOICES = [
        (KIND_TEXT, 'Text'),
        (KIND_IMAGE, 'Image'),
        (KIND_LINK, 'Link'),
        (KIND_VOICE, 'Voice'),
    ]

    forum = models.ForeignKey(
        Forum,
        on_delete=models.CASCADE,
        related_name='feed_posts',
    )
    author = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        related_name='feed_posts',
    )
    title = models.CharField(max_length=300, blank=True)

    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_TEXT)
    body_text = models.TextField(blank=True)
    body_json = models.JSONField(null=True, blank=True)  # ProseMirror document
    image_file = models.ImageField(upload_to='feed_posts/images/', null=True, blank=True)
    audio_file = models.FileField(upload_to='feed_posts/audio/', null=True, blank=True)
    link_url = models.URLField(blank=True)
    link_preview = models.JSONField(null=True, blank=True)

    # D14 — visibility scope
    visibility_scope = models.CharField(
        max_length=12,
        choices=_VISIBILITY_SCOPE_CHOICES,
        default='group',
    )

    # D6 — memory-value score (continuous; updated by signal events)
    memory_value_score = models.FloatField(default=0.0)

    # D8 — timeliness modifier (accelerates decay after this date)
    timeliness_date = models.DateField(null=True, blank=True)

    # D9 — creation-time signal (optional; seeds memory-value score)
    creation_signal = models.CharField(
        max_length=6,
        choices=_CREATION_SIGNAL_CHOICES,
        null=True,
        blank=True,
    )

    is_deleted = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['forum', '-created_at']),
            models.Index(fields=['author', '-created_at']),
            models.Index(fields=['forum', '-memory_value_score']),
            models.Index(fields=['kind', '-created_at']),
        ]

    def __str__(self):
        return self.title or f"FeedPost by {self.author} in {self.forum}"

    @property
    def post_count(self):
        return self.posts.filter(is_deleted=False).count()

    @property
    def last_post(self):
        return self.posts.filter(is_deleted=False).order_by('-created_at').first()

    @property
    def participants(self):
        return CustomUser.objects.filter(
            posts__feed_post=self,
            posts__is_deleted=False,
        ).distinct()


class Post(BaseModel):
    """
    Single contribution to a Discussion or FeedPost (D5).
    Exactly one of `discussion` or `feed_post` must be set.
    Inherits created_at, updated_at from BaseModel.
    """
    discussion = models.ForeignKey(
        Discussion,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="posts"
    )
    feed_post = models.ForeignKey(
        FeedPost,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="posts",
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

    # D10 — quoted reply (replaces nested threading)
    quoted_post = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="quotes",
    )
    quoted_passage = models.TextField(blank=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['discussion', 'created_at']),
            models.Index(fields=['feed_post', 'created_at']),
            models.Index(fields=['author', '-created_at']),
            models.Index(fields=['parent', 'created_at']),
        ]

    def clean(self):
        has_discussion = self.discussion_id is not None
        has_feed_post = self.feed_post_id is not None
        if has_discussion == has_feed_post:
            raise ValidationError("A Post must belong to exactly one of: Discussion or FeedPost.")

    @property
    def container(self):
        return self.discussion or self.feed_post

    def __str__(self):
        container = self.container
        label = getattr(container, 'title', None) or str(container)
        return f"Post by {self.author.username if self.author else 'Unknown'} in {label}"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new:
            container = self.container
            if container:
                container.save(update_fields=['updated_at'])

    @property
    def is_edited(self):
        if not self.updated_at:
            return False
        return (self.updated_at - self.created_at).total_seconds() > 60

    @property
    def is_author_distinguished(self):
        """True when the post author is the creator of the parent Discussion or FeedPost."""
        if self.discussion_id:
            return self.author_id == self.discussion.created_by_id
        if self.feed_post_id:
            return self.author_id == self.feed_post.author_id
        return False


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


class MemoryValueEvent(BaseModel):
    """
    Append-only log of memory-value score changes for Discussion and FeedPost (D6, D16).
    Enables auditing and retroactive reweighting — see ADR-0047 Section 12.
    """
    REACTION = 'reaction'
    REPLY = 'reply'
    QUOTED_REPLY = 'quoted_reply'
    AUTHOR_REPLY = 'author_distinguished_reply'
    CREATION_SIGNAL_EVENT = 'creation_signal'
    MODERATOR = 'moderator_adjustment'
    SUMMARY_APPROVED = 'summary_approved'
    DECAY = 'decay'

    EVENT_TYPE_CHOICES = [
        (REACTION, 'Reaction'),
        (REPLY, 'Reply'),
        (QUOTED_REPLY, 'Quoted Reply'),
        (AUTHOR_REPLY, 'Author-Distinguished Reply'),
        (CREATION_SIGNAL_EVENT, 'Creation-Time Signal'),
        (MODERATOR, 'Moderator Adjustment'),
        (SUMMARY_APPROVED, 'Summary Approved'),
        (DECAY, 'Scheduled Decay'),
    ]

    # GFK to Discussion or FeedPost (both use BigAutoField PKs)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    event_type = models.CharField(max_length=30, choices=EVENT_TYPE_CHOICES)
    delta = models.FloatField()
    actor = models.ForeignKey(
        CustomUser,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='memory_value_events',
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['content_type', 'object_id', '-created_at']),
            models.Index(fields=['event_type', '-created_at']),
        ]

    def __str__(self):
        return f"{self.event_type} +{self.delta} on {self.content_type}:{self.object_id}"
