from django.contrib import admin

from .models import Drop


@admin.register(Drop)
class DropAdmin(admin.ModelAdmin):
    list_display = ["handle", "weight", "is_archived", "expires_at", "created_at"]
    list_filter  = ["weight", "is_archived"]
    search_fields = ["handle", "content"]
    readonly_fields = ["id", "created_at", "updated_at"]
