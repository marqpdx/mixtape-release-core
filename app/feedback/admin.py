from django.contrib import admin

from .models import FeedbackBeacon, FeedbackItem


@admin.register(FeedbackBeacon)
class FeedbackBeaconAdmin(admin.ModelAdmin):
    list_display = ("key", "title", "is_active", "scope", "start_at", "end_at", "created_at")
    list_filter = ("is_active", "scope")
    search_fields = ("key", "title", "body_markdown")


@admin.register(FeedbackItem)
class FeedbackItemAdmin(admin.ModelAdmin):
    list_display = ("beacon", "kind", "status", "user", "created_at")
    list_filter = ("kind", "status")
    search_fields = ("message", "page_url")
