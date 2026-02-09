# profiles/api/urls.py

from django.urls import path

from .views import (
    MemberListView,
    MemberMeView,
    MemberDetailUpdateDeleteView,
)


# /api/members/

urlpatterns = [
    path("", MemberListView.as_view(), name="member-list"),
    path("me", MemberMeView.as_view(), name="member-me"),
    path("<str:username>", MemberDetailUpdateDeleteView.as_view(), name="member-detail"),
]
