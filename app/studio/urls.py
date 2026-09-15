# studio/urls.py
# No trailing slashes — follows project convention.

from django.urls import path
from . import views

urlpatterns = [
    # Personal Studio
    path("personal", views.PersonalStudioView.as_view(), name="studio-personal"),
    path("personal/groups", views.PersonalGroupsView.as_view(), name="studio-personal-groups"),
    path("personal/clio/dismiss", views.ClioDismissView.as_view(), name="studio-clio-dismiss"),
    path("personal/recurring-actions", views.PersonalRecurringActionsView.as_view(), name="studio-personal-recurring-actions"),
    path("personal/recurring-actions/<uuid:pk>", views.PersonalRecurringActionDetailView.as_view(), name="studio-personal-recurring-action-detail"),

    # Group Studio — Pulse / Canon / Command / Clients
    path("groups/<slug:slug>/pulse", views.GroupPulseView.as_view(), name="studio-group-pulse"),
    path("groups/<slug:slug>/canon", views.GroupCanonView.as_view(), name="studio-group-canon"),
    path("groups/<slug:slug>/command", views.GroupCommandView.as_view(), name="studio-group-command"),
    path("groups/<slug:slug>/clients", views.GroupClientsView.as_view(), name="studio-group-clients"),

    # Clio session surface
    path("clio/session", views.ClioSessionView.as_view(), name="studio-clio-session"),
    path("clio/scraps/<uuid:pk>", views.ClioScrapView.as_view(), name="studio-clio-scrap"),

    # RecurringAction admin
    path("groups/<slug:slug>/recurring-actions", views.GroupRecurringActionsView.as_view(), name="studio-group-recurring-actions"),
    path("groups/<slug:slug>/recurring-actions/<uuid:pk>", views.GroupRecurringActionDetailView.as_view(), name="studio-group-recurring-action-detail"),
]
