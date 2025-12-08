from django.contrib import admin

from .models import Tag, Category, ClassificationUsage


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    """Admin configuration for Tag model"""
    list_display = ('title', 'slug', 'usage_count', 'color', 'created_at')
    search_fields = ('title', 'summary')
    readonly_fields = ('slug', 'usage_count', 'created_at', 'updated_at', 'slug_history')
    ordering = ('title',)
    list_filter = ('created_at',)

    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'slug', 'summary')
        }),
        ('Display', {
            'fields': ('color',)
        }),
        ('Statistics', {
            'fields': ('usage_count',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at', 'slug_history'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """Admin configuration for Category model"""
    list_display = ('title', 'slug', 'usage_count', 'color', 'created_at')
    search_fields = ('title', 'summary')
    readonly_fields = ('slug', 'usage_count', 'created_at', 'updated_at', 'slug_history')
    ordering = ('title',)
    list_filter = ('created_at',)

    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'slug', 'summary')
        }),
        ('Display', {
            'fields': ('color',)
        }),
        ('Statistics', {
            'fields': ('usage_count',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at', 'slug_history'),
            'classes': ('collapse',)
        }),
    )


@admin.register(ClassificationUsage)
class ClassificationUsageAdmin(admin.ModelAdmin):
    """Admin configuration for ClassificationUsage model"""
    list_display = ('classification', 'classification_client', 'role', 'created_at')
    list_filter = ('classification_content_type', 'classification_client_content_type', 'created_at')
    search_fields = ('role',)
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ('Classification', {
            'fields': (
                'classification_content_type',
                'classification_object_id',
            )
        }),
        ('Applied To', {
            'fields': (
                'classification_client_content_type',
                'classification_client_object_id',
            )
        }),
        ('Additional', {
            'fields': ('role',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )