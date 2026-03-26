from django.contrib import admin

from .models import PublishEvent, ShareRecord, Source


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ["label", "kind", "tier_required", "group", "is_active"]
    list_filter = ["kind", "tier_required", "is_active"]
    search_fields = ["label", "kind"]


@admin.register(PublishEvent)
class PublishEventAdmin(admin.ModelAdmin):
    list_display = ["id", "writing_piece", "status", "scheduled_at", "executed_at", "created_by"]
    list_filter = ["status"]
    raw_id_fields = ["writing_piece", "created_by"]


@admin.register(ShareRecord)
class ShareRecordAdmin(admin.ModelAdmin):
    list_display = ["id", "source", "status", "canonical_url", "shared_at"]
    list_filter = ["status", "source__kind"]
    raw_id_fields = ["publish_event", "source"]
