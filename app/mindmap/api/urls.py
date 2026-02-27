# mindmap/api/urls.py

from django.urls import path

from . import views

app_name = "mindmap"

# parent url: api/mindmaps/

urlpatterns = [
    # MindMap CRUD
    path("", views.MindMapListCreateView.as_view(), name="mindmap-list-create"),
    path("<uuid:mindmap_id>", views.MindMapDetailView.as_view(), name="mindmap-detail"),

    # Nodes
    path("<uuid:mindmap_id>/nodes", views.MindMapNodeListCreateView.as_view(), name="node-list-create"),
    path("<uuid:mindmap_id>/nodes/<int:node_id>", views.MindMapNodeDetailView.as_view(), name="node-detail"),
    path("<uuid:mindmap_id>/nodes/bulk_upsert", views.MindMapNodeBulkUpsertView.as_view(), name="node-bulk-upsert"),
    path("<uuid:mindmap_id>/nodes/bulk_delete", views.MindMapNodeBulkDeleteView.as_view(), name="node-bulk-delete"),

    # Edges
    path("<uuid:mindmap_id>/edges", views.MindMapEdgeListCreateView.as_view(), name="edge-list-create"),
    path("<uuid:mindmap_id>/edges/<int:edge_id>", views.MindMapEdgeDetailView.as_view(), name="edge-detail"),
    path("<uuid:mindmap_id>/edges/bulk_upsert", views.MindMapEdgeBulkUpsertView.as_view(), name="edge-bulk-upsert"),
    path("<uuid:mindmap_id>/edges/bulk_delete", views.MindMapEdgeBulkDeleteView.as_view(), name="edge-bulk-delete"),

    # Attachments
    path("<uuid:mindmap_id>/nodes/<int:node_id>/attachments", views.MindMapNodeAttachmentListCreateView.as_view(), name="attachment-list-create"),
    path("<uuid:mindmap_id>/nodes/<int:node_id>/attachments/<int:attachment_id>", views.MindMapNodeAttachmentDetailView.as_view(), name="attachment-detail"),
]
