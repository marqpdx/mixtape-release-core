from django.contrib import admin

from .models import WritingMarkerOccurrence


@admin.register(WritingMarkerOccurrence)
class WritingMarkerOccurrenceAdmin(admin.ModelAdmin):
    list_display = ("id", "piece", "raw_name", "char_offset", "status", "created_at")
    list_filter = ("status", "raw_name")
    search_fields = ("raw_name", "label", "body")
    readonly_fields = ("affirmed_at", "dismissed_at", "created_at", "updated_at")
