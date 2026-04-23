from django.contrib import admin

from .models import LivingBook


@admin.register(LivingBook)
class LivingBookAdmin(admin.ModelAdmin):
    list_display = ("title", "trunk", "status", "created_by", "created_at")
    list_filter = ("status",)
    search_fields = ("title", "trunk__title")
    raw_id_fields = ("trunk", "created_by", "sponsor_content_type")
    readonly_fields = ("id", "created_at", "updated_at")
