from django.contrib import admin

from .models import AtriumSession, AtriumSessionEntry


class AtriumSessionEntryInline(admin.TabularInline):
    model = AtriumSessionEntry
    extra = 0
    readonly_fields = ("role", "content", "created_at")
    ordering = ("created_at",)


@admin.register(AtriumSession)
class AtriumSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "member", "title", "status", "last_activity_at", "created_at")
    list_filter = ("status",)
    search_fields = ("member__user__email", "title")
    readonly_fields = ("id", "created_at", "updated_at", "last_activity_at")
    inlines = [AtriumSessionEntryInline]


@admin.register(AtriumSessionEntry)
class AtriumSessionEntryAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "role", "created_at")
    list_filter = ("role",)
    readonly_fields = ("id", "created_at", "updated_at")
