# profiles/api/urls.py

from django.urls import path

from initiatives.api.views import ApertureInitiativeTypeaheadView, ApertureOrientationView
from .views import (
    MemberListView,
    MemberMeView,
    MemberDetailUpdateDeleteView,
    MemberContactView,
    MemberPreferencesView,
)


# /api/members/

urlpatterns = [
    path("", MemberListView.as_view(), name="member-list"),
    path("me", MemberMeView.as_view(), name="member-me"),
    path("me/preferences", MemberPreferencesView.as_view(), name="member-preferences"),
    path("me/aperture/orientation", ApertureOrientationView.as_view(), name="aperture-orientation"),
    path("me/aperture/initiatives", ApertureInitiativeTypeaheadView.as_view(), name="aperture-initiatives-typeahead"),
    path("<str:username>", MemberDetailUpdateDeleteView.as_view(), name="member-detail"),
    path("<str:username>/contact", MemberContactView.as_view(), name="member-contact"),
]
