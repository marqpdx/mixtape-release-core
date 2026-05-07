from django.contrib import admin

from .models import AgentPersona, HubCapture


@admin.register(HubCapture)
class HubCaptureAdmin(admin.ModelAdmin):
    list_display = ["kind", "status", "owner", "group", "body_preview", "created_at"]
    list_filter = ["kind", "status"]
    search_fields = ["body", "owner__username"]
    readonly_fields = ["promoted_to_content_type", "promoted_to_object_id", "resolved_at", "created_at", "updated_at"]

    def body_preview(self, obj):
        return obj.body[:60]
    body_preview.short_description = "body"


@admin.register(AgentPersona)
class AgentPersonaAdmin(admin.ModelAdmin):
    list_display = ["name", "role", "sponsor_content_type", "sponsor_object_id", "is_active", "created_at"]
    list_filter = ["is_active", "sponsor_content_type"]
    search_fields = ["name", "role", "tone_summary"]
    readonly_fields = ["sponsor_content_type", "sponsor_object_id", "created_at", "updated_at"]
    fieldsets = [
        (None, {"fields": ["name", "role", "is_active"]}),
        ("Sponsor", {"fields": ["sponsor_content_type", "sponsor_object_id"]}),
        ("Tone & Voice", {"fields": ["tone_summary", "tone_tags", "constraints", "writing_sample"]}),
        ("Timestamps", {"fields": ["created_at", "updated_at"]}),
    ]
