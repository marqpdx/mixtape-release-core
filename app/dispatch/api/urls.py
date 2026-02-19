# dispatch/api/urls.py

from django.urls import path

# from classifications.api.views import ClassificationUsageDeleteView
# from dispatch.api.views import PostCategoryListCreateView
from dispatch.api.views import (
    DispatchContentListCreateView,
    DispatchContentDetailView,
    DispatchContentYjsStateView,
    DispatchContentCollaboratorsView,
    DispatchContentVersionListCreateView,
    DispatchEditSessionListCreateView,
    DispatchOutlineListView,
    DispatchOutlineCreateView,
    DispatchOutlineDetailView,
)
from dispatch.models import Post


# parent: api/dispatch/
urlpatterns = [
    # path("posts", PostListCreateView.as_view(), name="post-list-create"),
    # path("posts/<slug:slug>", PostDetailView.as_view(), name="post-detail"),
    # path("posts/<slug:slug>/tags/", PostTagListCreateView.as_view(), name="post-tags"),
    # path("posts/<slug:slug>/categories/", PostCategoryListCreateView.as_view(), name="post-categories"),
    # path("posts/<slug:slug>/tags/<int:usage_id>/", ClassificationUsageDeleteView.as_view(model_class=Post), name="delete-post-tag"),

    # Collaborative content infrastructure (generic, not content-specific)
    path("content", DispatchContentListCreateView.as_view(), name="dispatch-content-list"),
    path("content/<uuid:id>", DispatchContentDetailView.as_view(), name="dispatch-content-detail"),
    path("content/<uuid:id>/yjs-state", DispatchContentYjsStateView.as_view(), name="dispatch-content-yjs-state"),
    path("content/<uuid:id>/collaborators", DispatchContentCollaboratorsView.as_view(), name="dispatch-content-collaborators"),
    path("versions", DispatchContentVersionListCreateView.as_view(), name="dispatch-content-versions"),
    path("sessions", DispatchEditSessionListCreateView.as_view(), name="dispatch-edit-sessions"),
    path("outline/<uuid:piece_id>", DispatchOutlineListView.as_view(), name="dispatch-outline-list"),
    path("outline", DispatchOutlineCreateView.as_view(), name="dispatch-outline-create"),
    path("outline/node/<uuid:id>", DispatchOutlineDetailView.as_view(), name="dispatch-outline-detail"),
]
