# folio/api/urls.py
# No trailing slashes — follows project convention.

from django.urls import path

from . import views

urlpatterns = [
    path("inceptions", views.FolioInceptionListCreateView.as_view(), name="folio-inception-list-create"),
    path("inceptions/<uuid:inception_id>", views.FolioInceptionDetailView.as_view(), name="folio-inception-detail"),
]
