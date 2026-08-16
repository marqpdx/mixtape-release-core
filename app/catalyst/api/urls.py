# catalyst/api/urls.py

from django.urls import path
from .views import ListRegistersView, MaterializeRegistersView, ParseFilesView, RegisterDetailView

urlpatterns = [
    path(
        "groups/<slug:slug>/materialize-registers/",
        MaterializeRegistersView.as_view(),
        name="catalyst-materialize-registers",
    ),
    path(
        "groups/<slug:slug>/registers/",
        ListRegistersView.as_view(),
        name="catalyst-list-registers",
    ),
    path(
        "groups/<slug:slug>/registers/<slug:register_slug>/",
        RegisterDetailView.as_view(),
        name="catalyst-register-detail",
    ),
    path(
        "groups/<slug:slug>/parse-files/",
        ParseFilesView.as_view(),
        name="catalyst-parse-files",
    ),
]
