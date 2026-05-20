from django.contrib import admin

from .models import Library, LibraryItem


class LibraryItemInline(admin.TabularInline):
    model = LibraryItem
    extra = 0
    fields = ['title', 'filename', 'folder_path', 'is_folder', 'size_bytes', 'is_featured', 'order_index']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(Library)
class LibraryAdmin(admin.ModelAdmin):
    list_display = ['title', 'slug', 'last_synced_at', 'created_at']
    search_fields = ['title', 'slug']
    readonly_fields = ['id', 'file_count', 'total_size_bytes', 'created_at', 'updated_at']
    inlines = [LibraryItemInline]
    fieldsets = [
        (None, {'fields': ['id', 'title', 'slug', 'summary', 'body']}),
        ('Owner', {'fields': ['owner_content_type', 'owner_object_id']}),
        ('Sync', {'fields': ['last_synced_at', 'file_count', 'total_size_bytes']}),
        ('Timestamps', {'fields': ['created_at', 'updated_at']}),
    ]

    def file_count(self, obj):
        return obj.file_count
    file_count.short_description = 'File count'

    def total_size_bytes(self, obj):
        return obj.total_size_bytes
    total_size_bytes.short_description = 'Total size (bytes)'
