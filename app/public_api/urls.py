# public_api/urls.py

from django.urls import path
from . import views, views_commons
from .views import PublicIssueView, CatalystIntakeView, PublicGroupLandingConfigView

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
        "members/<str:username>/writing",
        views.PublicMemberWritingView.as_view(),
        name="public-member-writing",
    ),
    path(
        "groups/<slug:slug>/writing",
        views.PublicGroupWritingView.as_view(),
        name="public-group-writing",
    ),
    path(
        "sites/writing",
        views.PublicSiteWritingView.as_view(),
        name="public-site-writing",
    ),
    path(
        "sites/writing/<uuid:piece_id>",
        views.PublicSiteWritingPieceView.as_view(),
        name="public-site-writing-piece",
    ),
    path(
        "groups/<slug:group_slug>/writing/<slug:slug>",
        views.PublicWritingPieceView.as_view(),
        name="public-group-writing-piece",
    ),
    path(
        "writing/issues/<slug:slug>",
        PublicIssueView.as_view(),
        name="public-writing-issue",
    ),
    # Group Public Landing config (Group Public Landing ADR — GP-2)
    path(
        "groups/<slug:slug>/public-config",
        PublicGroupLandingConfigView.as_view(),
        name="public-group-landing-config",
    ),
    # Crossroads Page — public read (DB-0002)
    path(
        "groups/<slug:slug>/page",
        views.PublicGroupPageView.as_view(),
        name="public-group-page",
    ),
    # Catalyst client intake (pilot — feature-flagged via INTAKE_FORM_ENABLED)
    path(
        "client-intake",
        CatalystIntakeView.as_view(),
        name="catalyst-client-intake",
    ),

    # Commons
    path(
        "commons",
        views_commons.PublicCommonsListView.as_view(),
        name="public-commons-list",
    ),
    path(
        "commons/<uuid:pk>",
        views_commons.PublicCommonsDetailView.as_view(),
        name="public-commons-detail",
    ),
]
