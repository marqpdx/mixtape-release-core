from django.contrib import admin

from .models import Relationship, RelationshipAnnotation, RelationshipType


@admin.register(RelationshipType)
class RelationshipTypeAdmin(admin.ModelAdmin):
    list_display = ("slug", "label", "domain", "is_directed", "allows_position", "uses_lifecycle")
    list_filter = ("domain", "is_directed", "uses_lifecycle")
    search_fields = ("slug", "label")
    ordering = ("domain", "slug")


@admin.register(Relationship)
class RelationshipAdmin(admin.ModelAdmin):
    list_display = ("id", "relationship_type", "source_content_type", "target_content_type", "status", "lifecycle", "created_by", "created_at")
    list_filter = ("status", "lifecycle", "visibility", "relationship_type__domain")
    search_fields = ("source_object_id", "target_object_id")
    raw_id_fields = ("created_by", "source_content_type", "target_content_type", "relationship_type")
    readonly_fields = ("created_at", "updated_at")


@admin.register(RelationshipAnnotation)
class RelationshipAnnotationAdmin(admin.ModelAdmin):
    list_display = ("relationship", "anchor_text", "created_at")
    raw_id_fields = ("relationship",)
    readonly_fields = ("created_at", "updated_at")
