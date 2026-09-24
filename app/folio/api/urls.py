# folio/api/urls.py
# No trailing slashes — follows project convention.

from django.urls import path

from . import views

urlpatterns = [
    path("inceptions", views.FolioInceptionListCreateView.as_view(), name="folio-inception-list-create"),
    path("inceptions/<uuid:inception_id>", views.FolioInceptionDetailView.as_view(), name="folio-inception-detail"),
    path(
        "inceptions/<uuid:inception_id>/analyze",
        views.FolioInceptionAnalyzeView.as_view(),
        name="folio-inception-analyze",
    ),
    path("folios/<uuid:folio_id>", views.FolioTitleDetailView.as_view(), name="folio-title-detail"),
    path(
        "material-candidates/<uuid:candidate_id>",
        views.FolioMaterialCandidateDetailView.as_view(),
        name="folio-material-candidate-detail",
    ),
    path(
        "material-candidates/<uuid:candidate_id>/confirm",
        views.FolioMaterialCandidateConfirmView.as_view(),
        name="folio-material-candidate-confirm",
    ),
    path(
        "material-candidates/<uuid:candidate_id>/reject",
        views.FolioMaterialCandidateRejectView.as_view(),
        name="folio-material-candidate-reject",
    ),
]
