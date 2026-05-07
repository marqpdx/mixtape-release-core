from django.contrib import admin

from .models import HubCapture


@admin.register(HubCapture)
class HubCaptureAdmin(admin.ModelAdmin):
    list_display = ["kind", "status", "owner", "group", "body_preview", "created_at"]
    list_filter = ["kind", "status"]
    search_fields = ["body", "owner__username"]
    readonly_fields = ["promoted_to_content_type", "promoted_to_object_id", "resolved_at", "created_at", "updated_at"]

    def body_preview(self, obj):
        return obj.body[:60]
    body_preview.short_description = "body"
