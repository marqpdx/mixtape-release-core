from django.contrib import admin
from .models import Scrap


@admin.register(Scrap)
class ScrapAdmin(admin.ModelAdmin):
    list_display = ["__str__", "intent_tag", "status", "remind_at", "created_at"]
    list_filter = ["intent_tag", "status", "intent_tag_misfit"]
    search_fields = ["body"]
    readonly_fields = ["created_at", "updated_at", "promoted_to_content_type", "promoted_to_object_id"]
    raw_id_fields = ["initiative", "aperture_log_entry"]
