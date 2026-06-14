from django.contrib import admin

from .models import Sprig


@admin.register(Sprig)
class SprigAdmin(admin.ModelAdmin):
    list_display  = ["__str__", "kind", "status", "source", "created_at"]
    list_filter   = ["kind", "status", "source"]
    search_fields = ["body", "transcript_text"]
    readonly_fields = [
        "id", "created_at", "updated_at",
        "sponsor_content_type", "sponsor_object_id",
        "transcript_status", "transcript_created_at", "transcript_error",
    ]
    raw_id_fields = ["author"]
