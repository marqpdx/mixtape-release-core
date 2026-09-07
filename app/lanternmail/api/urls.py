# lanternmail/api/urls.py

from django.urls import path
from . import views
from .views import lanternmail_posts_list, lanternmail_post_detail

# ============================================================================
# Group-scoped Lanternmail URL patterns
# Base path: /api/groups/<slug:slug>/lanternmail/
# ============================================================================

group_lanternmail_patterns = [
    # Mailing lists
    path('mailing-lists', views.get_group_mailing_lists, name='group-mailing-lists'),
    path('mailing-lists/create', views.create_group_mailing_list, name='create-group-mailing-list'),
    path('mailing-lists/<int:list_id>', views.get_mailing_list_detail, name='mailing-list-detail'),
    path('mailing-lists/<int:list_id>/toggle', views.toggle_mailing_list, name='toggle-mailing-list'),

    # Subscribers
    path('subscribers', views.get_group_members_all_lists, name='group-all-subscribers'),
    path('mailing-lists/<int:list_id>/subscribers', views.get_group_members_with_subscription_status, name='list-subscribers'),
    path('mailing-lists/<int:list_id>/subscribers/remove', views.remove_list_subscriber, name='remove-list-subscriber'),
    path('mailing-lists/<int:list_id>/invitations', views.send_list_invitations, name='send-invitations'),

    # Campaigns
    path('campaigns', views.list_group_campaigns, name='group-campaigns'),
    path('campaigns/create', views.create_group_campaign, name='group-campaigns-create'),
    path('campaigns/<int:campaign_id>/test', views.test_group_campaign, name='group-campaign-test'),
    path('campaigns/<int:campaign_id>/send', views.send_group_campaign, name='group-campaign-send'),

    # Posts
    path('posts', lanternmail_posts_list, name='group-lanternmail-posts'),
    path('posts/from-writing/<uuid:piece_id>', views.create_lanternmail_post_from_writing, name='group-lanternmail-post-from-writing'),
    path('posts/from-placement/<uuid:placement_id>', views.create_lanternmail_post_from_placement, name='group-lanternmail-post-from-placement'),
    path('posts/<int:post_id>', lanternmail_post_detail, name='group-lanternmail-post-detail'),
    path('posts/<int:post_id>/sync-campaign', views.sync_lanternmail_post_campaign, name='group-lanternmail-post-sync-campaign'),
    path('posts/<int:post_id>/test', views.test_lanternmail_post, name='group-lanternmail-post-test'),
    path('posts/<int:post_id>/send', views.send_lanternmail_post, name='group-lanternmail-post-send'),
]

# ============================================================================
# Global Lanternmail URL patterns (user-wide views)
# Base path: /api/lanternmail/
# ============================================================================

urlpatterns = [
    path('my-lists', views.list_user_mailing_lists, name='user-all-lists'),
    path('subscribe', views.public_subscribe, name='public-subscribe'),
    path('confirm', views.public_confirm_subscription, name='public-confirm-subscription'),
]
