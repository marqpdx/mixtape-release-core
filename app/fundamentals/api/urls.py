# fundamentals/api/urls.py
"""
URL configuration for Phase 4 Workbench API.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import MillDraftViewSet, ContentProfileConfigViewSet


router = DefaultRouter()
router.register(r'drafts', MillDraftViewSet, basename='milldraft')
router.register(r'profiles', ContentProfileConfigViewSet, basename='contentprofile')

urlpatterns = [
    path('', include(router.urls)),
]
