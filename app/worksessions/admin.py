from django.contrib import admin

from .models import (
    ArtifactMergeRecord,
    WorkSession,
    WorkSessionItem,
    WritingSurfaceDocument,
)


@admin.register(WritingSurfaceDocument)
class WritingSurfaceDocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "auto_save_count", "last_saved_at", "created_at")
    readonly_fields = ("id", "last_saved_at", "created_at", "updated_at")


@admin.register(WorkSession)
class WorkSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "owner",
        "anchor_content_type",
        "started_at",
        "ended_at",
        "is_active",
    )
    list_filter = ("anchor_content_type",)
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(WorkSessionItem)
class WorkSessionItemAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "content_type", "sequence")
    list_filter = ("content_type",)
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(ArtifactMergeRecord)
class ArtifactMergeRecordAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "source_content_type",
        "target_content_type",
        "merged_by",
        "created_at",
    )
    readonly_fields = ("id", "created_at", "updated_at")
