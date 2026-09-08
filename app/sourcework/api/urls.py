from django.urls import path

from .views import (
    ConnectionListCreateView,
    ConnectionGmailLabelsView,
    GoogleOAuthCallbackView,
    GoogleOAuthStartView,
    ProvisionalThingVerifyNameView,
    SourceGrantImportFromSourceView,
    SourceGrantImportLatestView,
    SourceGrantListCreateView,
    WorkingSetListView,
)


group_sourcework_patterns = [
    path("connections", ConnectionListCreateView.as_view(), name="sourcework-connections"),
    path("connections/<uuid:connection_id>/gmail-labels", ConnectionGmailLabelsView.as_view(), name="sourcework-gmail-labels"),
    path("google-oauth/start", GoogleOAuthStartView.as_view(), name="sourcework-google-oauth-start"),
    path("google-oauth/callback", GoogleOAuthCallbackView.as_view(), name="sourcework-google-oauth-callback"),
    path("source-grants", SourceGrantListCreateView.as_view(), name="sourcework-source-grants"),
    path("source-grants/<uuid:grant_id>/import-latest", SourceGrantImportLatestView.as_view(), name="sourcework-import-latest"),
    path("source-grants/<uuid:grant_id>/import-from-source", SourceGrantImportFromSourceView.as_view(), name="sourcework-import-from-source"),
    path("working-sets", WorkingSetListView.as_view(), name="sourcework-working-sets"),
    path("provisional-things/<uuid:thing_id>/verify-name", ProvisionalThingVerifyNameView.as_view(), name="sourcework-verify-name"),
]
