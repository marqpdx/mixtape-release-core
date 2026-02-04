from django.contrib import admin

from lists.models import List


@admin.register(List)
class ListAdmin(admin.ModelAdmin):
    list_display = ["title", "slug", "sponsor_display", "updated_at", "created_at"]
    list_filter = ["created_at", "updated_at"]
    search_fields = ["title", "slug", "body_text"]
    readonly_fields = ["id", "slug", "created_at", "updated_at"]
    ordering = ["-updated_at"]

    def sponsor_display(self, obj):
        return obj.sponsor_display

    sponsor_display.short_description = "Sponsor"
