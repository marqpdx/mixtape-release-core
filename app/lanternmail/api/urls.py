# lanternmail/api/urls.py

from django.urls import path
from . import views

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
