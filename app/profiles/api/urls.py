# profiles/api/urls.py

from django.urls import path

from .views import MemberDetailView, MemberListView


# /api/members/

urlpatterns = [
    path("", MemberListView.as_view(), name="member-list"),
    path("<str:username>", MemberDetailView.as_view(), name="member-detail"),
]
