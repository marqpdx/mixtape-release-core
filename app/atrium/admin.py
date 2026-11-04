from django.contrib import admin

from .models import CloudAgentSession, Dialogue, DialogueEntry


class DialogueEntryInline(admin.TabularInline):
    model = DialogueEntry
    extra = 0
    readonly_fields = ("role", "speaker", "status", "content", "created_at")
    ordering = ("created_at",)


@admin.register(Dialogue)
class DialogueAdmin(admin.ModelAdmin):
    list_display = ("id", "member", "title", "ai_provider", "status", "last_activity_at", "created_at")
    list_filter = ("status", "ai_provider")
    search_fields = ("member__user__email", "title")
    readonly_fields = ("id", "created_at", "updated_at", "last_activity_at")
    inlines = [DialogueEntryInline]


@admin.register(DialogueEntry)
class DialogueEntryAdmin(admin.ModelAdmin):
    list_display = ("id", "dialogue", "role", "speaker", "status", "error_code", "created_at")
    list_filter = ("role", "status", "speaker")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(CloudAgentSession)
class CloudAgentSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "dialogue",
        "provider",
        "status",
        "linux_user",
        "seen_through",
        "last_used_at",
        "created_at",
    )
    list_filter = ("provider", "status", "policy")
    search_fields = ("provider_session_id", "linux_user", "working_directory")
    readonly_fields = ("id", "created_at", "updated_at", "last_used_at")
