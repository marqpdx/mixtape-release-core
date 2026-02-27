# mindmap/admin.py

from django.contrib import admin

from .models import MindMap, MindMapEdge, MindMapNode, MindMapNodeAttachment


@admin.register(MindMap)
class MindMapAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "version", "share_mode", "created_at")
    list_filter = ("status", "share_mode")
    search_fields = ("title", "slug")


@admin.register(MindMapNode)
class MindMapNodeAdmin(admin.ModelAdmin):
    list_display = ("id", "mind_map", "node_type", "backing_kind", "title")
    list_filter = ("node_type", "backing_kind")


@admin.register(MindMapEdge)
class MindMapEdgeAdmin(admin.ModelAdmin):
    list_display = ("id", "mind_map", "source_node", "target_node", "edge_type")


@admin.register(MindMapNodeAttachment)
class MindMapNodeAttachmentAdmin(admin.ModelAdmin):
    list_display = ("id", "node", "kind", "title", "sort_order")
