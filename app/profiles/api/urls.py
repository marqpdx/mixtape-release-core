# profiles/api/urls.py

from django.urls import path

from initiatives.api.views import ApertureOrientationView
from .views import (
    MemberListView,
    MemberMeView,
    MemberDetailUpdateDeleteView,
)


# /api/members/

urlpatterns = [
    path("", MemberListView.as_view(), name="member-list"),
    path("me", MemberMeView.as_view(), name="member-me"),
    path("me/aperture/orientation", ApertureOrientationView.as_view(), name="aperture-orientation"),
    path("<str:username>", MemberDetailUpdateDeleteView.as_view(), name="member-detail"),
]
