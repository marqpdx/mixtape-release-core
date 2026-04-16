from django.contrib import admin

from .models import Collection, CollectionItem


class CollectionItemInline(admin.TabularInline):
    model = CollectionItem
    extra = 0
    fields = ['title', 'content_type', 'content_object_id', 'order_index', 'is_folder', 'is_featured', 'is_hidden']
    readonly_fields = ['content_type', 'content_object_id']


@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ['title', 'slug', 'visibility', 'scope', 'submitted_by', 'created_at']
    list_filter = ['visibility', 'scope']
    search_fields = ['title', 'summary']
    readonly_fields = ['id', 'slug', 'created_at', 'updated_at']
    inlines = [CollectionItemInline]


@admin.register(CollectionItem)
class CollectionItemAdmin(admin.ModelAdmin):
    list_display = ['id', 'collection', 'title', 'is_folder', 'order_index', 'is_featured']
    list_filter = ['is_folder', 'is_featured', 'is_hidden']
    readonly_fields = ['id', 'created_at', 'updated_at']
