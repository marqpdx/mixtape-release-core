from django.contrib import admin

from .models import StoredFile


@admin.register(StoredFile)
class StoredFileAdmin(admin.ModelAdmin):
    list_display = ("id", "file_name", "file_type", "file_size", "uploaded_by", "created_at")
    search_fields = ("file_name", "file_path")
    list_filter = ("file_type", "created_at")
