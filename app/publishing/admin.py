from django.contrib import admin
from .models import PublicationGroup, ContentPlacement


@admin.register(PublicationGroup)
class PublicationGroupAdmin(admin.ModelAdmin):
    list_display = ['id', 'source', 'created_by', 'created_at']
    list_filter = ['created_at']
    search_fields = ['note', 'source_object_id']
    readonly_fields = ['id', 'created_at']
    raw_id_fields = ['created_by']


@admin.register(ContentPlacement)
class ContentPlacementAdmin(admin.ModelAdmin):
    list_display = ['id', 'source', 'target', 'channel', 'visibility', 'follow_updates', 'created_at']
    list_filter = ['channel', 'visibility', 'follow_updates', 'created_at']
    search_fields = ['source_object_id', 'target_object_id']
    readonly_fields = ['id', 'created_at']
    raw_id_fields = ['publication_group', 'placed_by']
