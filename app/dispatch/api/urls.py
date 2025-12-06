# dispatch/api/urls.py

from django.urls import path

# from classifications.api.views import ClassificationUsageDeleteView
# from dispatch.api.views import PostCategoryListCreateView
from dispatch.api.views import (
    DispatchDocumentListCreateView,
    DispatchDocumentDetailView,
    DispatchDocumentYjsStateView,
    DispatchDocumentCollaboratorsView,
    DispatchDocumentVersionListCreateView,
    DispatchEditSessionListCreateView,
)
from dispatch.models import Post


# parent: api/dispatch/
urlpatterns = [
    # path("posts", PostListCreateView.as_view(), name="post-list-create"),
    # path("posts/<slug:slug>", PostDetailView.as_view(), name="post-detail"),
    # path("posts/<slug:slug>/tags/", PostTagListCreateView.as_view(), name="post-tags"),
    # path("posts/<slug:slug>/categories/", PostCategoryListCreateView.as_view(), name="post-categories"),
    # path("posts/<slug:slug>/tags/<int:usage_id>/", ClassificationUsageDeleteView.as_view(model_class=Post), name="delete-post-tag"),

    path("documents", DispatchDocumentListCreateView.as_view(), name="dispatch-documents"),
    path("documents/<slug:slug>", DispatchDocumentDetailView.as_view(), name="dispatch-documents-detail"),
    path("documents/<slug:slug>/yjs-state", DispatchDocumentYjsStateView.as_view(), name="dispatch-documents-yjs-state"),
    path("documents/<slug:slug>/collaborators", DispatchDocumentCollaboratorsView.as_view(), name="dispatch-documents-collaborators"),
    path("versions", DispatchDocumentVersionListCreateView.as_view(), name="dispatch-versions"),
    path("sessions", DispatchEditSessionListCreateView.as_view(), name="dispatch-sessions"),
]
