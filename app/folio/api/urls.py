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
    path("folios", views.FolioListCreateView.as_view(), name="folio-list-create"),
    path("folios/<uuid:folio_id>", views.FolioTitleDetailView.as_view(), name="folio-title-detail"),
    path("folios/<uuid:folio_id>/notes", views.FolioNoteListCreateView.as_view(), name="folio-note-list-create"),
    path("entities", views.WriterEntityListView.as_view(), name="folio-writer-entities"),
    path(
        "folios/<uuid:folio_id>/notes/facets",
        views.FolioNoteFacetsView.as_view(),
        name="folio-note-facets",
    ),
    path(
        "folios/<uuid:folio_id>/notes/<uuid:note_id>/related",
        views.FolioNoteRelatedView.as_view(),
        name="folio-note-related",
    ),
    path(
        "folios/<uuid:folio_id>/notes/<uuid:note_id>/mentions/<int:index>",
        views.FolioNoteMentionView.as_view(),
        name="folio-note-mention",
    ),
    path(
        "folios/<uuid:folio_id>/notes/search",
        views.FolioNoteSearchView.as_view(),
        name="folio-note-search",
    ),
    path(
        "folios/<uuid:folio_id>/notes/<uuid:note_id>",
        views.FolioNoteDetailView.as_view(),
        name="folio-note-detail",
    ),
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
