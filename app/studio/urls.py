# studio/urls.py
# No trailing slashes — follows project convention.

from django.urls import path
from . import views

urlpatterns = [
    # Personal Studio
    path("personal", views.PersonalStudioView.as_view(), name="studio-personal"),
    path("personal/groups", views.PersonalGroupsView.as_view(), name="studio-personal-groups"),

    # Group Studio — Pulse / Canon / Command / Clients
    path("groups/<slug:slug>/pulse", views.GroupPulseView.as_view(), name="studio-group-pulse"),
    path("groups/<slug:slug>/canon", views.GroupCanonView.as_view(), name="studio-group-canon"),
    path("groups/<slug:slug>/command", views.GroupCommandView.as_view(), name="studio-group-command"),
    path("groups/<slug:slug>/clients", views.GroupClientsView.as_view(), name="studio-group-clients"),
]
