from django.urls import path
from .views import (
    WorkTableEntryArchiveView,
    WorkTableEntryDeleteView,
    WorkTableProseView,
    WorkTableStreamView,
)

urlpatterns = [
    path("stream/", WorkTableStreamView.as_view(), name="worktable-stream"),
    path("prose/", WorkTableProseView.as_view(), name="worktable-prose"),
    path("entries/<uuid:entry_id>/archive/", WorkTableEntryArchiveView.as_view(), name="worktable-entry-archive"),
    path("entries/<uuid:entry_id>/", WorkTableEntryDeleteView.as_view(), name="worktable-entry-delete"),
]
