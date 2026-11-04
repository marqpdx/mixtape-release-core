# profiles/api/urls.py

from django.urls import path

from initiatives.api.views import InitiativeTypeaheadView, InitiativeOrientationView
from .views import (
    MemberListView,
    MemberMeView,
    MemberDetailUpdateDeleteView,
    MemberContactView,
    MemberPreferencesView,
    MemberVoiceUploadView,
)


# /api/members/

urlpatterns = [
    path("", MemberListView.as_view(), name="member-list"),
    path("me", MemberMeView.as_view(), name="member-me"),
    path("me/voice", MemberVoiceUploadView.as_view(), name="member-voice"),
    path("me/preferences", MemberPreferencesView.as_view(), name="member-preferences"),
    path("me/initiatives/orientation", InitiativeOrientationView.as_view(), name="initiative-orientation"),
    path("me/initiatives/search", InitiativeTypeaheadView.as_view(), name="initiative-typeahead"),
    # Former Aperture paths, kept only until the renamed frontend is deployed (ST-3 Part B, 2026-11-04). Remove after.
    path("me/aperture/orientation", InitiativeOrientationView.as_view()),
    path("me/aperture/initiatives", InitiativeTypeaheadView.as_view()),
    path("<str:username>", MemberDetailUpdateDeleteView.as_view(), name="member-detail"),
    path("<str:username>/contact", MemberContactView.as_view(), name="member-contact"),
]
