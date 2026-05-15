# profiles/api/profile_revamp_urls.py

from django.urls import path
from .profile_revamp_views import (
    PublicProfileView,
    MeProfileView,
    MeSectionsView,
    MePinnedView,
    MeNowPlayingView,
    MeQAView,
    MeLinksView,
    MePublishView,
)

# Included at:
#   /api/profiles/   → public_profile_patterns
#   /api/me/profile/ → me_profile_patterns

public_profile_patterns = [
    path('<str:username>', PublicProfileView.as_view(), name='public-profile-detail'),
]

me_profile_patterns = [
    path('new',              MeProfileView.as_view(),    name='me-profile-revamp'),
    path('new/sections',     MeSectionsView.as_view(),   name='me-profile-sections'),
    path('new/pinned',       MePinnedView.as_view(),     name='me-profile-pinned'),
    path('new/now-playing',  MeNowPlayingView.as_view(), name='me-profile-now-playing'),
    path('new/qa',           MeQAView.as_view(),         name='me-profile-qa'),
    path('new/links',        MeLinksView.as_view(),      name='me-profile-links'),
    path('new/publish',      MePublishView.as_view(),    name='me-profile-publish'),
]
