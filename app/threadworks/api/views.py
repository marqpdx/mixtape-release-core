# threadworks/api/views.py

from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.shortcuts import get_object_or_404
from django.db.models import Q, Count, Max
from django.utils import timezone
from django.http import Http404
from django.contrib.contenttypes.models import ContentType

from django.contrib.auth import get_user_model
from groups.models import Group
from groups.permissions import canUserModerateGroupUser, isGroupMemberUser

CustomUser = get_user_model()

from ..models import (
    Forum, Discussion, Post, PostReaction, PostFlag,
    DiscussionView, ForumNotification
)
from .serializers import (
    ForumSerializer,
    ForumCreateSerializer,
    DiscussionSerializer,
    DiscussionDetailSerializer,
    DiscussionCreateSerializer,
    PostSerializer,
    PostCreateSerializer,
    PostReactionSerializer,
    PostFlagSerializer,
    NotificationSerializer,
    ParticipantSerializer,
    ForumAudienceMemberSerializer,
)

# ============================================================================
# PAGINATION
# ============================================================================

class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'per_page'
    max_page_size = 100


# ============================================================================
# SITE-WIDE FORUM VIEWS
# ============================================================================

class ForumListCreateView(generics.ListCreateAPIView):
    """
    List public forums or create a new one.
    GET /api/threadworks/
    POST /api/threadworks/
    """
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = StandardResultsSetPagination

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return ForumCreateSerializer
        return ForumSerializer

    def get_queryset(self):
        # Show only public forums at site level
        return Forum.objects.filter(
            visibility='public',
            is_archived=False
        ).order_by('-updated_at')

    def perform_create(self, serializer):
        # Set sponsor to current user
        serializer.save(
            submitted_by=self.request.user,
            sponsor_content_type=ContentType.objects.get_for_model(self.request.user.__class__),
            sponsor_object_id=self.request.user.id,
        )


class ForumDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update, or delete a forum.
    GET /api/threadworks/{forum_slug}/
    PATCH /api/threadworks/{forum_slug}/
    DELETE /api/threadworks/{forum_slug}/
    """
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    serializer_class = ForumSerializer
    lookup_field = 'slug'
    lookup_url_kwarg = 'forum_slug'

    def get_queryset(self):
        return Forum.objects.filter(is_archived=False)

    def perform_update(self, serializer):
        # Only creator or staff can update
        forum = self.get_object()
        if self.request.user != forum.submitted_by and not self.request.user.is_staff:
            raise permissions.PermissionDenied("You can only edit your own forums.")
        serializer.save()

    def perform_destroy(self, instance):
        # Only creator or staff can delete
        if self.request.user != instance.submitted_by and not self.request.user.is_staff:
            raise permissions.PermissionDenied("You can only delete your own forums.")
        instance.delete()


# ============================================================================
# SITE-WIDE DISCUSSION VIEWS
# ============================================================================

class DiscussionListCreateView(generics.ListCreateAPIView):
    """
    List discussions in a forum or create a new one.
    GET /api/threadworks/{forum_slug}/discussions/
    POST /api/threadworks/{forum_slug}/discussions/
    """
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = StandardResultsSetPagination

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return DiscussionCreateSerializer
        return DiscussionSerializer

    def get_queryset(self):
        forum_slug = self.kwargs['forum_slug']
        forum = get_object_or_404(Forum, slug=forum_slug, is_archived=False)
        return forum.discussions.filter(is_deleted=False).order_by('-updated_at')

    def get_serializer_context(self):
        context = super().get_serializer_context()
        forum_slug = self.kwargs['forum_slug']
        context['forum'] = get_object_or_404(Forum, slug=forum_slug, is_archived=False)
        return context

    def perform_create(self, serializer):
        forum = self.get_serializer_context()['forum']
        serializer.save(forum=forum, created_by=self.request.user)


class DiscussionDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update, or delete a discussion.
    GET /api/threadworks/{forum_slug}/discussions/{discussion_slug}/
    PATCH /api/threadworks/{forum_slug}/discussions/{discussion_slug}/
    DELETE /api/threadworks/{forum_slug}/discussions/{discussion_slug}/
    """
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    serializer_class = DiscussionDetailSerializer
    lookup_field = 'slug'
    lookup_url_kwarg = 'discussion_slug'

    def get_queryset(self):
        forum_slug = self.kwargs['forum_slug']
        forum = get_object_or_404(Forum, slug=forum_slug, is_archived=False)
        return forum.discussions.filter(is_deleted=False)

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        discussion = self.get_object()

        # Mark as viewed
        if request.user.is_authenticated:
            DiscussionView.objects.update_or_create(
                discussion=discussion,
                user=request.user,
                defaults={'updated_at': timezone.now()}
            )

        return response

    def perform_update(self, serializer):
        discussion = self.get_object()
        if self.request.user != discussion.created_by and not self.request.user.is_staff:
            raise permissions.PermissionDenied("You can only edit your own discussions.")
        serializer.save()

    def perform_destroy(self, instance):
        if self.request.user != instance.created_by and not self.request.user.is_staff:
            raise permissions.PermissionDenied("You can only delete your own discussions.")
        instance.is_deleted = True
        instance.save()


# ============================================================================
# SITE-WIDE POST VIEWS
# ============================================================================

class PostListCreateView(generics.ListCreateAPIView):
    """
    List posts in a discussion or create a new one.
    GET /api/threadworks/{forum_slug}/discussions/{discussion_slug}/posts/
    POST /api/threadworks/{forum_slug}/discussions/{discussion_slug}/posts/
    """
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = StandardResultsSetPagination
    serializer_class = PostSerializer

    def get_queryset(self):
        forum_slug = self.kwargs['forum_slug']
        discussion_slug = self.kwargs['discussion_slug']

        forum = get_object_or_404(Forum, slug=forum_slug, is_archived=False)
        discussion = get_object_or_404(
            forum.discussions.all(),
            slug=discussion_slug,
            is_deleted=False
        )

        return discussion.posts.filter(is_deleted=False).order_by('created_at')

    def perform_create(self, serializer):
        forum_slug = self.kwargs['forum_slug']
        discussion_slug = self.kwargs['discussion_slug']

        forum = get_object_or_404(Forum, slug=forum_slug, is_archived=False)
        discussion = get_object_or_404(
            forum.discussions.all(),
            slug=discussion_slug,
            is_deleted=False
        )

        if discussion.is_locked and not self.request.user.is_staff:
            raise permissions.PermissionDenied("This discussion is locked.")

        post = serializer.save(discussion=discussion, author=self.request.user)

        # Fire activity producer if forum is group-sponsored
        try:
            group = forum.sponsor
            if group and isinstance(group, Group):
                from threadworks.producers import on_threadworks_post_created
                on_threadworks_post_created(
                    post=post, discussion=discussion, forum=forum, group=group,
                )
        except Exception:
            pass  # Don't block post creation if activity fails


class PostDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update, or delete a post.
    GET /api/threadworks/{forum_slug}/discussions/{discussion_slug}/posts/{post_id}/
    PATCH /api/threadworks/{forum_slug}/discussions/{discussion_slug}/posts/{post_id}/
    DELETE /api/threadworks/{forum_slug}/discussions/{discussion_slug}/posts/{post_id}/
    """
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    serializer_class = PostSerializer
    lookup_field = 'id'
    lookup_url_kwarg = 'post_id'

    def get_queryset(self):
        forum_slug = self.kwargs['forum_slug']
        discussion_slug = self.kwargs['discussion_slug']

        forum = get_object_or_404(Forum, slug=forum_slug, is_archived=False)
        discussion = get_object_or_404(
            forum.discussions.all(),
            slug=discussion_slug,
            is_deleted=False
        )

        return discussion.posts.filter(is_deleted=False)

    def perform_update(self, serializer):
        post = self.get_object()
        if self.request.user != post.author and not self.request.user.is_staff:
            raise permissions.PermissionDenied("You can only edit your own posts.")
        serializer.save()

    def perform_destroy(self, instance):
        if self.request.user != instance.author and not self.request.user.is_staff:
            raise permissions.PermissionDenied("You can only delete your own posts.")
        instance.is_deleted = True
        instance.save()


# ============================================================================
# REACTIONS & MODERATION
# ============================================================================

class PostReactionView(generics.CreateAPIView):
    """Add or remove a reaction to a post"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PostReactionSerializer

    def post(self, request, post_id):
        post = get_object_or_404(Post, id=post_id, is_deleted=False)
        reaction = request.data.get('reaction')

        # Remove existing reaction from this user
        PostReaction.objects.filter(post=post, user=request.user).delete()

        # Add new reaction if provided
        if reaction:
            PostReaction.objects.create(
                post=post,
                user=request.user,
                reaction=reaction
            )
            return Response({'status': 'reaction_added'}, status=status.HTTP_201_CREATED)

        return Response({'status': 'reaction_removed'}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def lock_discussion(request, forum_slug, discussion_slug):
    """Lock or unlock a discussion (staff only)"""
    if not request.user.is_staff:
        raise permissions.PermissionDenied("Only staff can lock discussions.")

    forum = get_object_or_404(Forum, slug=forum_slug, is_archived=False)
    discussion = get_object_or_404(
        forum.discussions.all(),
        slug=discussion_slug,
        is_deleted=False
    )

    discussion.is_locked = not discussion.is_locked
    discussion.save()

    return Response({
        'status': 'discussion_locked' if discussion.is_locked else 'discussion_unlocked',
        'is_locked': discussion.is_locked
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def pin_discussion(request, forum_slug, discussion_slug):
    """Pin or unpin a discussion (staff only)"""
    if not request.user.is_staff:
        raise permissions.PermissionDenied("Only staff can pin discussions.")

    forum = get_object_or_404(Forum, slug=forum_slug, is_archived=False)
    discussion = get_object_or_404(
        forum.discussions.all(),
        slug=discussion_slug,
        is_deleted=False
    )

    # Toggle between pinned and active
    discussion.status = 'pinned' if discussion.status != 'pinned' else 'active'
    discussion.save()

    return Response({
        'status': 'discussion_pinned' if discussion.status == 'pinned' else 'discussion_unpinned',
        'status_value': discussion.status
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def flag_post(request, post_id):
    """Flag a post for moderation"""
    post = get_object_or_404(Post, id=post_id, is_deleted=False)
    reason = request.data.get('reason', 'other')
    description = request.data.get('description', '')

    flag, created = PostFlag.objects.get_or_create(
        post=post,
        user=request.user,
        defaults={'reason': reason, 'description': description}
    )

    if created:
        return Response({'status': 'post_flagged'}, status=status.HTTP_201_CREATED)
    return Response({'status': 'already_flagged'}, status=status.HTTP_200_OK)


# Alias for compatibility
FlagPostView = flag_post


# ============================================================================
# SEARCH & DISCOVERY
# ============================================================================

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def search_forum(request, forum_slug):
    """Search within a forum"""
    query = request.GET.get('q', '').strip()
    if not query:
        return Response({'results': [], 'query': query, 'total_results': 0})

    forum = get_object_or_404(Forum, slug=forum_slug, is_archived=False)

    # Search discussions by title and posts by content
    discussions = forum.discussions.filter(
        is_deleted=False,
        posts__is_deleted=False
    ).filter(
        Q(posts__content__icontains=query) |
        Q(title__icontains=query)
    ).distinct().select_related('created_by')[:50]

    results = []
    for discussion in discussions:
        results.append({
            'type': 'discussion',
            'discussion_slug': discussion.slug,
            'discussion_title': discussion.title,
            'creator': {
                'id': str(discussion.created_by.id),
                'username': discussion.created_by.username,
            },
            'created_at': discussion.created_at,
        })

    return Response({'results': results, 'query': query, 'total_results': len(results)})


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def search_discussion(request, forum_slug, discussion_slug):
    """Search within a discussion"""
    query = request.GET.get('q', '').strip()
    if not query:
        return Response({'results': [], 'query': query, 'total_results': 0})

    forum = get_object_or_404(Forum, slug=forum_slug, is_archived=False)
    discussion = get_object_or_404(
        forum.discussions.all(),
        slug=discussion_slug,
        is_deleted=False
    )

    posts = discussion.posts.filter(
        is_deleted=False,
        content__icontains=query
    ).select_related('author').order_by('-created_at')

    results = []
    for post in posts[:50]:
        results.append({
            'type': 'post',
            'post_id': str(post.id),
            'author': post.author.username if post.author else 'Unknown',
            'content': post.content[:200] + '...' if len(post.content) > 200 else post.content,
            'created_at': post.created_at,
        })

    return Response({'results': results, 'query': query, 'total_results': len(results)})


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def forum_participants(request, forum_slug):
    """Get recent participants in a forum"""
    forum = get_object_or_404(Forum, slug=forum_slug, is_archived=False)
    participants = forum.recent_participants

    serializer = ParticipantSerializer(
        participants,
        many=True,
        context={'forum': forum, 'request': request}
    )

    return Response({'participants': serializer.data})


# ============================================================================
# VIEW TRACKING
# ============================================================================

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def mark_discussion_viewed(request, forum_slug, discussion_slug):
    """Mark a discussion as viewed"""
    forum = get_object_or_404(Forum, slug=forum_slug, is_archived=False)
    discussion = get_object_or_404(
        forum.discussions.all(),
        slug=discussion_slug,
        is_deleted=False
    )

    DiscussionView.objects.update_or_create(
        discussion=discussion,
        user=request.user,
        defaults={'updated_at': timezone.now()}
    )

    return Response({'status': 'discussion_marked_viewed'})


# ============================================================================
# NOTIFICATIONS
# ============================================================================

class NotificationListView(generics.ListAPIView):
    """List notifications for current user"""
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    serializer_class = NotificationSerializer

    def get_queryset(self):
        return ForumNotification.objects.filter(
            user=self.request.user
        ).order_by('-created_at')


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def mark_notification_read(request, pk):
    """Mark notification as read"""
    notification = get_object_or_404(
        ForumNotification,
        id=pk,
        user=request.user
    )

    notification.is_read = True
    notification.save()

    return Response({'status': 'notification_marked_read'})


# ============================================================================
# USER ACTIVITY
# ============================================================================

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def user_forum_activity(request, user_id):
    """Get a user's forum activity summary"""
    from django.contrib.auth import get_user_model
    User = get_user_model()

    user = get_object_or_404(User, id=user_id)

    # Get recent posts
    recent_posts = Post.objects.filter(
        author=user,
        is_deleted=False
    ).select_related('discussion', 'discussion__forum').order_by('-created_at')[:10]

    # Get recent discussions created by user
    recent_discussions = Discussion.objects.filter(
        created_by=user,
        is_deleted=False
    ).select_related('forum').order_by('-created_at')[:10]

    return Response({
        'user': {
            'id': str(user.id),
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
        },
        'recent_posts': PostSerializer(recent_posts, many=True).data,
        'recent_discussions': DiscussionSerializer(recent_discussions, many=True).data,
        'total_posts': user.posts.filter(is_deleted=False).count(),
        'total_discussions': user.discussions.filter(is_deleted=False).count(),
    })


# ============================================================================
# GROUP-SCOPED VIEWS
# ============================================================================

def get_group_or_404(slug):
    """Get group by slug or raise 404"""
    return get_object_or_404(Group, slug=slug)


def get_group_forum_queryset(group):
    """Get forums filtered by group as sponsor"""
    return Forum.objects.filter(
        sponsor_content_type=ContentType.objects.get_for_model(Group),
        sponsor_object_id=group.id
    ).order_by('-updated_at')


def _user_can_access_forum(user, forum):
    """Return True if the user has audience access to this forum."""
    if forum.audience_type == 'all_members':
        return True
    return forum.audience_members.filter(pk=user.pk).exists()


class GroupForumListCreateView(generics.ListCreateAPIView):
    """
    List all forums for a group, or create a new one.
    GET /api/groups/<slug>/threadworks/
    POST /api/groups/<slug>/threadworks/
    """
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = StandardResultsSetPagination

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return ForumCreateSerializer
        return ForumSerializer

    def get_queryset(self):
        group = get_group_or_404(self.kwargs['slug'])
        qs = get_group_forum_queryset(group)
        user = self.request.user
        if user.is_authenticated:
            # Show all_members forums + subset forums the user belongs to
            qs = qs.filter(
                Q(audience_type='all_members') |
                Q(audience_type='subset', audience_members=user)
            ).distinct()
        else:
            qs = qs.filter(audience_type='all_members')
        return qs

    def perform_create(self, serializer):
        group = get_group_or_404(self.kwargs['slug'])

        can_manage = (
            canUserModerateGroupUser(self.request.user, group)
            or isGroupMemberUser(self.request.user, group)
            and hasattr(self.request.user, 'group_permissions')
        )
        if not canUserModerateGroupUser(self.request.user, group) and not self.request.user.is_staff:
            raise permissions.PermissionDenied("You don't have permission to create forums in this group.")

        serializer.save(
            submitted_by=self.request.user,
            sponsor_content_type=ContentType.objects.get_for_model(Group),
            sponsor_object_id=group.id,
        )


class GroupForumAudienceView(generics.GenericAPIView):
    """
    PATCH /api/groups/<slug>/threadworks/<forum_slug>/audience
    Update a forum's audience type, auto_add flag, and member list.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ForumSerializer

    def get_forum(self):
        group = get_group_or_404(self.kwargs['slug'])
        return get_object_or_404(get_group_forum_queryset(group), slug=self.kwargs['forum_slug'])

    def patch(self, request, slug, forum_slug):
        group = get_group_or_404(slug)
        if not canUserModerateGroupUser(request.user, group) and not request.user.is_staff:
            raise permissions.PermissionDenied("You don't have permission to manage this forum's audience.")

        forum = self.get_forum()

        audience_type = request.data.get('audience_type')
        auto_add = request.data.get('auto_add_new_members')
        member_ids = request.data.get('member_ids')

        update_fields = []
        if audience_type in ('all_members', 'subset'):
            forum.audience_type = audience_type
            update_fields.append('audience_type')
        if auto_add is not None:
            forum.auto_add_new_members = bool(auto_add)
            update_fields.append('auto_add_new_members')
        if update_fields:
            forum.save(update_fields=update_fields)

        if member_ids is not None and forum.audience_type == 'subset':
            users = CustomUser.objects.filter(id__in=member_ids)
            forum.audience_members.set(users)
        elif forum.audience_type == 'all_members':
            forum.audience_members.clear()

        return Response(ForumSerializer(forum, context={'request': request}).data)


class GroupForumDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update, or delete a forum in a group.
    GET /api/groups/<slug>/threadworks/<forum_slug>/
    PATCH /api/groups/<slug>/threadworks/<forum_slug>/
    DELETE /api/groups/<slug>/threadworks/<forum_slug>/
    """
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    serializer_class = ForumSerializer
    lookup_field = 'slug'
    lookup_url_kwarg = 'forum_slug'

    def get_queryset(self):
        group = get_group_or_404(self.kwargs['slug'])
        return get_group_forum_queryset(group)

    def perform_update(self, serializer):
        group = get_group_or_404(self.kwargs['slug'])
        if not canUserModerateGroupUser(self.request.user, group) and not self.request.user.is_staff:
            raise permissions.PermissionDenied("You don't have permission to edit forums in this group.")
        serializer.save()

    def perform_destroy(self, instance):
        group = get_group_or_404(self.kwargs['slug'])
        if not canUserModerateGroupUser(self.request.user, group) and not self.request.user.is_staff:
            raise permissions.PermissionDenied("You don't have permission to delete forums in this group.")
        instance.delete()


class GroupDiscussionListCreateView(generics.ListCreateAPIView):
    """
    List discussions in a group forum or create a new one.
    GET /api/groups/<slug>/threadworks/<forum_slug>/discussions/
    POST /api/groups/<slug>/threadworks/<forum_slug>/discussions/
    """
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = StandardResultsSetPagination

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return DiscussionCreateSerializer
        return DiscussionSerializer

    def get_queryset(self):
        group = get_group_or_404(self.kwargs['slug'])
        forum = get_object_or_404(
            get_group_forum_queryset(group),
            slug=self.kwargs['forum_slug']
        )
        return forum.discussions.filter(is_deleted=False).order_by('-updated_at')

    def get_serializer_context(self):
        context = super().get_serializer_context()
        group = get_group_or_404(self.kwargs['slug'])
        context['forum'] = get_object_or_404(
            get_group_forum_queryset(group),
            slug=self.kwargs['forum_slug']
        )
        return context

    def perform_create(self, serializer):
        forum = self.get_serializer_context()['forum']
        serializer.save(forum=forum, created_by=self.request.user)


class GroupDiscussionDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update, or delete a discussion in a group forum.
    GET /api/groups/<slug>/threadworks/<forum_slug>/discussions/<discussion_slug>/
    PATCH /api/groups/<slug>/threadworks/<forum_slug>/discussions/<discussion_slug>/
    DELETE /api/groups/<slug>/threadworks/<forum_slug>/discussions/<discussion_slug>/
    """
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    serializer_class = DiscussionDetailSerializer
    lookup_field = 'slug'
    lookup_url_kwarg = 'discussion_slug'

    def get_queryset(self):
        group = get_group_or_404(self.kwargs['slug'])
        forum = get_object_or_404(
            get_group_forum_queryset(group),
            slug=self.kwargs['forum_slug']
        )
        return forum.discussions.filter(is_deleted=False)

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        discussion = self.get_object()

        if request.user.is_authenticated:
            DiscussionView.objects.update_or_create(
                discussion=discussion,
                user=request.user,
                defaults={'updated_at': timezone.now()}
            )

        return response

    def perform_update(self, serializer):
        discussion = self.get_object()
        if self.request.user != discussion.created_by:
            group = get_group_or_404(self.kwargs['slug'])
            if not canUserModerateGroupUser(self.request.user, group) and not self.request.user.is_staff:
                raise permissions.PermissionDenied("You can only edit your own discussions.")
        serializer.save()

    def perform_destroy(self, instance):
        if self.request.user != instance.created_by:
            group = get_group_or_404(self.kwargs['slug'])
            if not canUserModerateGroupUser(self.request.user, group) and not self.request.user.is_staff:
                raise permissions.PermissionDenied("You can only delete your own discussions.")
        instance.is_deleted = True
        instance.save()


class GroupPostListCreateView(generics.ListCreateAPIView):
    """
    List posts in a group forum discussion or create a new one.
    GET /api/groups/<slug>/threadworks/<forum_slug>/discussions/<discussion_slug>/posts/
    POST /api/groups/<slug>/threadworks/<forum_slug>/discussions/<discussion_slug>/posts/
    """
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = StandardResultsSetPagination
    serializer_class = PostSerializer

    def get_queryset(self):
        group = get_group_or_404(self.kwargs['slug'])
        forum = get_object_or_404(
            get_group_forum_queryset(group),
            slug=self.kwargs['forum_slug']
        )
        discussion = get_object_or_404(
            forum.discussions.all(),
            slug=self.kwargs['discussion_slug'],
            is_deleted=False
        )
        return discussion.posts.filter(is_deleted=False).order_by('created_at')

    def perform_create(self, serializer):
        group = get_group_or_404(self.kwargs['slug'])
        forum = get_object_or_404(
            get_group_forum_queryset(group),
            slug=self.kwargs['forum_slug']
        )
        discussion = get_object_or_404(
            forum.discussions.all(),
            slug=self.kwargs['discussion_slug'],
            is_deleted=False
        )

        if discussion.is_locked and not self.request.user.is_staff:
            raise permissions.PermissionDenied("This discussion is locked.")

        post = serializer.save(discussion=discussion, author=self.request.user)

        # Fire activity producer for group-scoped post
        try:
            from threadworks.producers import on_threadworks_post_created
            on_threadworks_post_created(
                post=post, discussion=discussion, forum=forum, group=group,
            )
        except Exception:
            pass  # Don't block post creation if activity fails


class GroupPostDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update, or delete a post in a group forum discussion.
    GET /api/groups/<slug>/threadworks/<forum_slug>/discussions/<discussion_slug>/posts/<post_id>/
    PATCH /api/groups/<slug>/threadworks/<forum_slug>/discussions/<discussion_slug>/posts/<post_id>/
    DELETE /api/groups/<slug>/threadworks/<forum_slug>/discussions/<discussion_slug>/posts/<post_id>/
    """
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    serializer_class = PostSerializer
    lookup_field = 'id'
    lookup_url_kwarg = 'post_id'

    def get_queryset(self):
        group = get_group_or_404(self.kwargs['slug'])
        forum = get_object_or_404(
            get_group_forum_queryset(group),
            slug=self.kwargs['forum_slug']
        )
        discussion = get_object_or_404(
            forum.discussions.all(),
            slug=self.kwargs['discussion_slug'],
            is_deleted=False
        )
        return discussion.posts.filter(is_deleted=False)

    def perform_update(self, serializer):
        post = self.get_object()
        if self.request.user != post.author:
            group = get_group_or_404(self.kwargs['slug'])
            if not canUserModerateGroupUser(self.request.user, group) and not self.request.user.is_staff:
                raise permissions.PermissionDenied("You can only edit your own posts.")
        serializer.save()

    def perform_destroy(self, instance):
        if self.request.user != instance.author:
            group = get_group_or_404(self.kwargs['slug'])
            if not canUserModerateGroupUser(self.request.user, group) and not self.request.user.is_staff:
                raise permissions.PermissionDenied("You can only delete your own posts.")
        instance.is_deleted = True
        instance.save()