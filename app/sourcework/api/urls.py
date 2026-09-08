from django.urls import path

from .views import (
    ConnectionListCreateView,
    ProvisionalThingVerifyNameView,
    SourceGrantImportLatestView,
    SourceGrantListCreateView,
    WorkingSetListView,
)


group_sourcework_patterns = [
    path("connections", ConnectionListCreateView.as_view(), name="sourcework-connections"),
    path("source-grants", SourceGrantListCreateView.as_view(), name="sourcework-source-grants"),
    path("source-grants/<uuid:grant_id>/import-latest", SourceGrantImportLatestView.as_view(), name="sourcework-import-latest"),
    path("working-sets", WorkingSetListView.as_view(), name="sourcework-working-sets"),
    path("provisional-things/<uuid:thing_id>/verify-name", ProvisionalThingVerifyNameView.as_view(), name="sourcework-verify-name"),
]
