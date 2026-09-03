from django.contrib import admin

from .models import AtriumSession, AtriumSessionEntry, CloudAgentSession


class AtriumSessionEntryInline(admin.TabularInline):
    model = AtriumSessionEntry
    extra = 0
    readonly_fields = ("role", "content", "created_at")
    ordering = ("created_at",)


@admin.register(AtriumSession)
class AtriumSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "member", "title", "ai_provider", "status", "last_activity_at", "created_at")
    list_filter = ("status", "ai_provider")
    search_fields = ("member__user__email", "title")
    readonly_fields = ("id", "created_at", "updated_at", "last_activity_at")
    inlines = [AtriumSessionEntryInline]


@admin.register(AtriumSessionEntry)
class AtriumSessionEntryAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "role", "created_at")
    list_filter = ("role",)
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(CloudAgentSession)
class CloudAgentSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "atrium_session",
        "provider",
        "status",
        "linux_user",
        "last_used_at",
        "created_at",
    )
    list_filter = ("provider", "status", "policy")
    search_fields = ("provider_session_id", "linux_user", "working_directory")
    readonly_fields = ("id", "created_at", "updated_at", "last_used_at")
