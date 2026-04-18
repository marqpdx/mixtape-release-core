from django.contrib import admin

from .models import ArtifactRelation


@admin.register(ArtifactRelation)
class ArtifactRelationAdmin(admin.ModelAdmin):
    list_display = ("id", "verb", "status", "created_by", "created_at")
    list_filter = ("verb", "status")
    search_fields = ("note",)
    readonly_fields = ("acknowledged_at", "acknowledged_by", "mutual_at", "created_at", "updated_at")
