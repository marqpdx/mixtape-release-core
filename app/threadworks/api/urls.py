# threadworks/api/urls.py

from django.urls import path
from . import views
from .sponsor_views import (
    SponsorForumsListView,
    SponsorDiscussionsListView,
)

app_name = 'threadworks'

# Site-wide threadworks endpoints
site_urlpatterns = [
    # Sponsor-based queries (generic for groups and members)
    path('forums', SponsorForumsListView.as_view(), name='sponsor-forums-list'),
    path('discussions', SponsorDiscussionsListView.as_view(), name='sponsor-discussions-list'),

    # Forums
    path('', views.ForumListCreateView.as_view(), name='forum-list-create'),
    path('<slug:forum_slug>', views.ForumDetailView.as_view(), name='forum-detail'),

    # Discussions
    path('<slug:forum_slug>/discussions', views.DiscussionListCreateView.as_view(), name='discussion-list-create'),
    path('<slug:forum_slug>/discussions/<slug:discussion_slug>', views.DiscussionDetailView.as_view(), name='discussion-detail'),

    # Posts
    path('<slug:forum_slug>/discussions/<slug:discussion_slug>/posts', views.PostListCreateView.as_view(), name='post-list-create'),
    path('<slug:forum_slug>/discussions/<slug:discussion_slug>/posts/<uuid:post_id>', views.PostDetailView.as_view(), name='post-detail'),

    # Reactions
    path('posts/<uuid:post_id>/reactions', views.PostReactionView.as_view(), name='post-reactions'),

    # Moderation
    path('posts/<uuid:post_id>/flag', views.flag_post, name='flag-post'),
    path('<slug:forum_slug>/discussions/<slug:discussion_slug>/lock', views.lock_discussion, name='lock-discussion'),
    path('<slug:forum_slug>/discussions/<slug:discussion_slug>/pin', views.pin_discussion, name='pin-discussion'),

    # Search
    path('<slug:forum_slug>/search', views.search_forum, name='forum-search'),
    path('<slug:forum_slug>/discussions/<slug:discussion_slug>/search', views.search_discussion, name='discussion-search'),

    # Participants
    path('<slug:forum_slug>/participants', views.forum_participants, name='forum-participants'),

    # View tracking
    path('<slug:forum_slug>/discussions/<slug:discussion_slug>/view', views.mark_discussion_viewed, name='mark-discussion-viewed'),

    # Notifications
    path('notifications', views.NotificationListView.as_view(), name='notification-list'),
    path('notifications/<uuid:pk>/read', views.mark_notification_read, name='mark-notification-read'),

    # User activity
    path('users/<uuid:user_id>/activity', views.user_forum_activity, name='user-activity'),
]

# Group-scoped threadworks endpoints
# These are included in groups/api/urls.py as:
# path('<slug:slug>/threadworks', include('threadworks.api.urls', namespace='group-threadworks'), {'is_group': True})
group_threadworks_patterns = [
    # Forums (group-scoped)
    path('', views.GroupForumListCreateView.as_view(), name='group-forum-list-create'),
    path('<slug:forum_slug>', views.GroupForumDetailView.as_view(), name='group-forum-detail'),
    path('<slug:forum_slug>/audience', views.GroupForumAudienceView.as_view(), name='group-forum-audience'),

    # Discussions (group-scoped)
    path('<slug:forum_slug>/discussions', views.GroupDiscussionListCreateView.as_view(), name='group-discussion-list-create'),
    path('<slug:forum_slug>/discussions/<slug:discussion_slug>', views.GroupDiscussionDetailView.as_view(), name='group-discussion-detail'),

    # Posts (group-scoped)
    path('<slug:forum_slug>/discussions/<slug:discussion_slug>/posts', views.GroupPostListCreateView.as_view(), name='group-post-list-create'),
    path('<slug:forum_slug>/discussions/<slug:discussion_slug>/posts/<uuid:post_id>', views.GroupPostDetailView.as_view(), name='group-post-detail'),
]

urlpatterns = site_urlpatterns