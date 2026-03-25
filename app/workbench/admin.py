# workbench/admin.py

from django.contrib import admin

from .models import WorkingItem, WorkingItemMembership


class WorkingItemMembershipInline(admin.TabularInline):
    model = WorkingItemMembership
    extra = 0
    readonly_fields = ("id", "piece_content_type", "piece_object_id", "content_snapshot", "position", "created_at")


@admin.register(WorkingItem)
class WorkingItemAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "author", "target_writing_kind", "created_at", "updated_at")
    list_filter = ("status", "target_writing_kind")
    search_fields = ("title", "body")
    readonly_fields = ("id", "slug", "promoted_to", "promoted_at", "created_at", "updated_at")
    inlines = [WorkingItemMembershipInline]


@admin.register(WorkingItemMembership)
class WorkingItemMembershipAdmin(admin.ModelAdmin):
    list_display = ("working_item", "piece_content_type", "piece_object_id", "position", "created_at")
    readonly_fields = ("id", "created_at")
