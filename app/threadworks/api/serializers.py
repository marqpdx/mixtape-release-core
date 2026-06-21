# threadworks/api/serializers.py

from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.db.models import Count

from ..models import DiscussionView, FeedPost, Forum, Discussion, Post, PostReaction, PostFlag, ForumNotification

CustomUser = get_user_model()


# ============================================================================
# USER SERIALIZERS (Embedded)
# ============================================================================

class ThreadworksUserSerializer(serializers.ModelSerializer):
    """Minimal user info for threadworks context"""
    # avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        # fields = ['id', 'username', 'first_name', 'last_name', 'avatar_url']
        fields = ['id', 'username', 'first_name', 'last_name', ]

    # TODO fix this
    # def get_avatar_url(self, obj):
    #     """Get avatar URL from user profile if available"""
    #     if hasattr(obj, 'profile') and hasattr(obj.profile, 'avatar') and obj.profile.avatar:
    #         return obj.profile.avatar
    #     # Fallback to UI avatars service
    #     return f"https://ui-avatars.com/api/?name={obj.first_name}+{obj.last_name}&background=random"


# ============================================================================
# POST SERIALIZERS
# ============================================================================

class PostSerializer(serializers.ModelSerializer):
    """Post with author and metadata"""
    author = ThreadworksUserSerializer(read_only=True)
    reaction_counts = serializers.SerializerMethodField()
    user_reaction = serializers.SerializerMethodField()
    is_author_distinguished = serializers.BooleanField(read_only=True)

    class Meta:
        model = Post
        fields = [
            'id',
            'author',
            'content',
            'created_at',
            'updated_at',
            'is_edited',
            'parent_id',
            'discussion_id',
            'feed_post_id',
            'quoted_post_id',
            'quoted_passage',
            'is_author_distinguished',
            'reaction_counts',
            'user_reaction',
        ]
        read_only_fields = [
            'id',
            'author',
            'created_at',
            'updated_at',
            'is_edited',
            'discussion_id',
            'feed_post_id',
            'is_author_distinguished',
        ]

    def get_reaction_counts(self, obj):
        """Get count of each reaction type"""
        return obj.reactions.values('reaction').annotate(
            count=Count('id')
        ).order_by('reaction')

    def get_user_reaction(self, obj):
        """Get current user's reaction if any"""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            reaction = obj.reactions.filter(user=request.user).first()
            return reaction.reaction if reaction else None
        return None


class PostCreateSerializer(serializers.ModelSerializer):
    """Minimal serializer for creating posts"""
    quoted_post = serializers.PrimaryKeyRelatedField(
        queryset=Post.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Post
        fields = ['content', 'parent', 'quoted_post', 'quoted_passage']

    def create(self, validated_data):
        validated_data['author'] = self.context['request'].user
        return super().create(validated_data)


# ============================================================================
# DISCUSSION SERIALIZERS
# ============================================================================

class DiscussionSerializer(serializers.ModelSerializer):
    """List view - minimal discussion info"""
    created_by = ThreadworksUserSerializer(read_only=True)
    post_count = serializers.SerializerMethodField()
    last_post = PostSerializer(read_only=True)
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Discussion
        fields = [
            'id',
            'slug',
            'title',
            'description',
            'created_at',
            'updated_at',
            'created_by',
            'post_count',
            'status',
            'is_locked',
            'last_post',
            'unread_count',
            'visibility_scope',
            'memory_value_score',
            'timeliness_date',
            'creation_signal',
            'summary',
        ]
        read_only_fields = [
            'id',
            'slug',
            'created_at',
            'updated_at',
            'created_by',
            'post_count',
            'last_post',
            'memory_value_score',
        ]

    def get_post_count(self, obj):
        return obj.posts.filter(is_deleted=False).count()

    def get_unread_count(self, obj):
        """Count posts since user last viewed"""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            try:
                view = DiscussionView.objects.get(discussion=obj, user=request.user)
                return obj.posts.filter(
                    created_at__gt=view.updated_at,
                    is_deleted=False
                ).count()
            except DiscussionView.DoesNotExist:
                return obj.posts.filter(is_deleted=False).count()
        return 0


class DiscussionDetailSerializer(serializers.ModelSerializer):
    """Detail view - includes all posts"""
    created_by = ThreadworksUserSerializer(read_only=True)
    posts = PostSerializer(many=True, read_only=True)
    post_count = serializers.SerializerMethodField()
    participants = serializers.SerializerMethodField()

    class Meta:
        model = Discussion
        fields = [
            'id',
            'slug',
            'title',
            'description',
            'created_at',
            'updated_at',
            'created_by',
            'posts',
            'post_count',
            'status',
            'is_locked',
            'participants',
            'visibility_scope',
            'memory_value_score',
            'timeliness_date',
            'creation_signal',
            'summary',
            'summary_pending',
            'summary_pending_delta',
            'summary_pending_substantive',
        ]
        read_only_fields = [
            'id',
            'slug',
            'created_at',
            'updated_at',
            'created_by',
            'posts',
            'post_count',
            'participants',
            'memory_value_score',
        ]

    def get_post_count(self, obj):
        return obj.posts.filter(is_deleted=False).count()

    def get_participants(self, obj):
        """Get unique authors who posted"""
        participants = obj.participants
        return ThreadworksUserSerializer(participants, many=True).data


class DiscussionCreateSerializer(serializers.Serializer):
    """Minimal serializer for creating discussions with initial post"""
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    content = serializers.CharField()
    visibility_scope = serializers.ChoiceField(
        choices=['circle', 'group', 'crossroads'],
        required=False,
        default='group',
    )
    creation_signal = serializers.ChoiceField(
        choices=['low', 'medium', 'high'],
        required=False,
        allow_null=True,
        allow_blank=True,
        default=None,
    )
    timeliness_date = serializers.DateField(required=False, allow_null=True)

    def create(self, validated_data):
        """Create discussion and initial post"""
        forum = self.context['forum']
        user = self.context['request'].user

        discussion = Discussion.objects.create(
            forum=forum,
            title=validated_data['title'],
            description=validated_data.get('description', ''),
            created_by=user,
            visibility_scope=validated_data.get('visibility_scope', 'group'),
            creation_signal=validated_data.get('creation_signal') or None,
            timeliness_date=validated_data.get('timeliness_date'),
        )

        Post.objects.create(
            discussion=discussion,
            author=user,
            content=validated_data['content'],
        )

        return discussion

    def to_representation(self, instance):
        """Return as DiscussionSerializer format"""
        return DiscussionSerializer(instance, context=self.context).data


# ============================================================================
# FORUM SERIALIZERS
# ============================================================================

class ForumAudienceMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'first_name', 'last_name']


class ForumSerializer(serializers.ModelSerializer):
    """List view - includes discussions but not posts"""
    submitted_by = ThreadworksUserSerializer(read_only=True)
    discussions = DiscussionSerializer(many=True, read_only=True)
    recent_participants = ThreadworksUserSerializer(many=True, read_only=True)
    discussion_count = serializers.SerializerMethodField()
    feed_post_count = serializers.SerializerMethodField()
    visibility_label = serializers.SerializerMethodField()
    audience_member_count = serializers.SerializerMethodField()
    audience_members = ForumAudienceMemberSerializer(many=True, read_only=True)

    class Meta:
        model = Forum
        fields = [
            'id',
            'slug',
            'title',
            'description',
            'visibility',
            'visibility_label',
            'created_at',
            'updated_at',
            'submitted_by',
            'discussions',
            'discussion_count',
            'feed_post_count',
            'recent_participants',
            'last_activity',
            'is_archived',
            'is_contained_circle',
            'audience_type',
            'auto_add_new_members',
            'audience_member_count',
            'audience_members',
        ]
        read_only_fields = [
            'id',
            'slug',
            'created_at',
            'updated_at',
            'submitted_by',
            'discussion_count',
            'recent_participants',
            'last_activity',
            'audience_member_count',
            'audience_members',
        ]

    def get_discussion_count(self, obj):
        return obj.discussions.filter(is_deleted=False).count()

    def get_feed_post_count(self, obj):
        return obj.feed_posts.filter(is_deleted=False).count()

    def get_visibility_label(self, obj):
        labels = {
            'public': 'Public',
            'members': 'Members Only',
            'group': 'Group Only',
        }
        return labels.get(obj.visibility, obj.visibility)

    def get_audience_member_count(self, obj):
        if obj.audience_type == 'subset':
            return obj.audience_members.count()
        return None


class ForumCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating forums"""
    sponsor_type = serializers.CharField(write_only=True, required=False)
    sponsor_slug = serializers.CharField(write_only=True, required=False)
    member_ids = serializers.ListField(
        child=serializers.UUIDField(), write_only=True, required=False
    )

    class Meta:
        model = Forum
        fields = [
            'title',
            'description',
            'visibility',
            'sponsor_type',
            'sponsor_slug',
            'audience_type',
            'auto_add_new_members',
            'member_ids',
        ]

    def create(self, validated_data):
        from django.contrib.contenttypes.models import ContentType

        sponsor_type = validated_data.pop('sponsor_type', None)
        sponsor_slug = validated_data.pop('sponsor_slug', None)
        member_ids = validated_data.pop('member_ids', [])

        if sponsor_type and sponsor_slug:
            if sponsor_type == 'group':
                from groups.models import Group
                sponsor = Group.objects.get(slug=sponsor_slug)
                content_type = ContentType.objects.get_for_model(Group)
            elif sponsor_type == 'member':
                from django.contrib.auth import get_user_model
                User = get_user_model()
                sponsor = User.objects.get(username=sponsor_slug)
                content_type = ContentType.objects.get_for_model(User)
            else:
                raise serializers.ValidationError("sponsor_type must be 'group' or 'member'")

            validated_data['sponsor_content_type'] = content_type
            validated_data['sponsor_object_id'] = sponsor.id

        validated_data['submitted_by'] = self.context['request'].user
        forum = super().create(validated_data)

        # Populate subset audience members if provided
        if forum.audience_type == 'subset' and member_ids:
            users = CustomUser.objects.filter(id__in=member_ids)
            forum.audience_members.set(users)

        return forum


# ============================================================================
# REACTIONS & MODERATION
# ============================================================================

class PostReactionSerializer(serializers.ModelSerializer):
    """Reaction data"""
    user = ThreadworksUserSerializer(read_only=True)

    class Meta:
        model = PostReaction
        fields = ['id', 'user', 'reaction', 'created_at']
        read_only_fields = ['id', 'user', 'created_at']


class PostFlagSerializer(serializers.ModelSerializer):
    """Flag data for moderation"""
    user = ThreadworksUserSerializer(read_only=True)
    resolved_by = ThreadworksUserSerializer(read_only=True)

    class Meta:
        model = PostFlag
        fields = [
            'id',
            'user',
            'reason',
            'description',
            'created_at',
            'is_resolved',
            'resolved_by',
            'resolved_at',
        ]
        read_only_fields = [
            'id',
            'user',
            'created_at',
            'resolved_by',
            'resolved_at',
        ]


# ============================================================================
# NOTIFICATIONS
# ============================================================================

class NotificationSerializer(serializers.ModelSerializer):
    """Forum notification"""
    forum = ForumSerializer(read_only=True)
    discussion = DiscussionSerializer(read_only=True)
    post = PostSerializer(read_only=True)

    class Meta:
        model = ForumNotification
        fields = [
            'id',
            'forum',
            'discussion',
            'post',
            'notification_type',
            'is_read',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'forum',
            'discussion',
            'post',
            'created_at',
        ]


# ============================================================================
# SEARCH & VIEW TRACKING
# ============================================================================

class SearchResultSerializer(serializers.Serializer):
    """Generic search result"""
    type = serializers.CharField()
    id = serializers.CharField()
    slug = serializers.CharField()
    title = serializers.CharField()
    creator = ThreadworksUserSerializer()
    created_at = serializers.DateTimeField()


class ParticipantSerializer(serializers.ModelSerializer):
    """Forum participant info"""
    last_activity = serializers.SerializerMethodField()
    post_count = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'first_name', 'last_name', 'last_activity', 'post_count']

    def get_last_activity(self, obj):
        forum = self.context.get('forum')
        if forum:
            latest = obj.posts.filter(
                discussion__forum=forum,
                is_deleted=False
            ).order_by('-created_at').first()
            return latest.created_at if latest else None
        return None

    def get_post_count(self, obj):
        forum = self.context.get('forum')
        if forum:
            return obj.posts.filter(
                discussion__forum=forum,
                is_deleted=False
            ).count()
        return 0


# ============================================================================
# FEED POST
# ============================================================================

class FeedPostSerializer(serializers.ModelSerializer):
    """FeedPost read serializer — artifact-centric content (D4)"""
    author = ThreadworksUserSerializer(read_only=True)
    post_count = serializers.SerializerMethodField()
    image_file = serializers.ImageField(read_only=True, use_url=True)
    audio_file = serializers.FileField(read_only=True, use_url=True)

    class Meta:
        model = FeedPost
        fields = [
            'id',
            'author',
            'title',
            'kind',
            'body_text',
            'body_json',
            'image_file',
            'audio_file',
            'link_url',
            'link_preview',
            'visibility_scope',
            'memory_value_score',
            'timeliness_date',
            'creation_signal',
            'is_deleted',
            'created_at',
            'updated_at',
            'post_count',
        ]
        read_only_fields = [
            'id',
            'author',
            'memory_value_score',
            'created_at',
            'updated_at',
            'post_count',
        ]

    def get_post_count(self, obj):
        return obj.posts.filter(is_deleted=False).count()


class FeedPostCreateSerializer(serializers.ModelSerializer):
    """FeedPost create/update serializer"""
    class Meta:
        model = FeedPost
        fields = [
            'title',
            'kind',
            'body_text',
            'body_json',
            'link_url',
            'visibility_scope',
            'timeliness_date',
            'creation_signal',
        ]


class FeedPostDetailSerializer(FeedPostSerializer):
    """FeedPost detail — includes posts (replies)"""
    posts = PostSerializer(many=True, read_only=True)

    class Meta(FeedPostSerializer.Meta):
        fields = FeedPostSerializer.Meta.fields + ['posts']