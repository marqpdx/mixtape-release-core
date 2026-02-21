# public_api/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path(
        "groups",
        views.PublicGroupsListView.as_view(),
        name="public-groups-list",
    ),
    path(
        "groups/<slug:slug>",
        views.PublicGroupDetailView.as_view(),
        name="public-group-detail",
    ),
    path(
        "groups/<slug:slug>/admission-status",
        views.PublicGroupAdmissionStatusView.as_view(),
        name="public-group-admission-status",
    ),
    path(
        "groups/<slug:slug>/courses",
        views.PublicGroupCoursesView.as_view(),
        name="public-group-courses",
    ),
    path(
        "groups/<slug:slug>/courses/<slug:course_slug>",
        views.PublicCourseDetailView.as_view(),
        name="public-course-detail",
    ),
    path(
        "members/<str:username>",
        views.PublicMemberProfileView.as_view(),
        name="public-member-profile",
    ),
    path(
        "members/<str:username>/shelves",
        views.PublicMemberShelvesView.as_view(),
        name="public-member-shelves",
    ),
    path(
        "writing/<slug:slug>",
        views.PublicWritingPieceView.as_view(),
        name="public-writing-piece",
    ),
]
