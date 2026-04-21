from django.contrib import admin

from .models import ArtifactRelation, WritingMarkerOccurrence


@admin.register(ArtifactRelation)
class ArtifactRelationAdmin(admin.ModelAdmin):
    list_display = ("id", "verb", "status", "created_by", "created_at")
    list_filter = ("verb", "status")
    search_fields = ("note",)
    readonly_fields = ("acknowledged_at", "acknowledged_by", "mutual_at", "created_at", "updated_at")


@admin.register(WritingMarkerOccurrence)
class WritingMarkerOccurrenceAdmin(admin.ModelAdmin):
    list_display = ("id", "piece", "raw_name", "char_offset", "status", "created_at")
    list_filter = ("status", "raw_name")
    search_fields = ("raw_name", "label", "body")
    readonly_fields = ("affirmed_at", "dismissed_at", "created_at", "updated_at")
