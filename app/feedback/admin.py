from django.contrib import admin

from .models import FeedbackBeacon, FeedbackItem, FeedbackAttachment


@admin.register(FeedbackBeacon)
class FeedbackBeaconAdmin(admin.ModelAdmin):
    list_display = ("key", "title", "is_active", "scope", "start_at", "end_at", "created_at")
    list_filter = ("is_active", "scope")
    search_fields = ("key", "title", "body_markdown")


@admin.register(FeedbackItem)
class FeedbackItemAdmin(admin.ModelAdmin):
    list_display = ("beacon", "kind", "status", "user", "work_area", "created_at")
    list_filter = ("kind", "status")
    search_fields = ("message", "page_url", "work_area", "voice_transcript")
    raw_id_fields = ("voice_file", "media_capture")


@admin.register(FeedbackAttachment)
class FeedbackAttachmentAdmin(admin.ModelAdmin):
    list_display = ("feedback_item", "stored_file", "created_at")
    raw_id_fields = ("feedback_item", "stored_file")
