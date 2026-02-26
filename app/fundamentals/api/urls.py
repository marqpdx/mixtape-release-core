# fundamentals/api/urls.py
"""
URL configuration for Phase 4 Workbench API + Follow system.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .follow_views import (
    FollowingListView,
    FollowStatusView,
    FollowUserView,
    UnfollowUserView,
)
from .views import MillDraftViewSet, ContentProfileConfigViewSet


router = DefaultRouter()
router.register(r'drafts', MillDraftViewSet, basename='milldraft')
router.register(r'profiles', ContentProfileConfigViewSet, basename='contentprofile')

urlpatterns = [
    path('', include(router.urls)),

    # Follows
    path('follows', FollowUserView.as_view(), name='follow-create'),
    path('follows/list', FollowingListView.as_view(), name='follow-list'),
    path('follows/<uuid:user_id>', UnfollowUserView.as_view(), name='follow-delete'),
    path('follows/<uuid:user_id>/status', FollowStatusView.as_view(), name='follow-status'),
]
