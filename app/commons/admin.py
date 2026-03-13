# commons/admin.py

from django.contrib import admin

from .models import CommonsItem, Filament


@admin.register(CommonsItem)
class CommonsItemAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "item_type",
        "curation_status",
        "location_name",
        "recommended_by",
        "created_at",
    ]
    list_filter = ["curation_status", "item_type"]
    search_fields = ["title", "summary", "location_name", "website"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(Filament)
class FilamentAdmin(admin.ModelAdmin):
    list_display = ["source", "relation_type", "target", "created_at"]
    list_filter = ["relation_type"]
