from django.contrib import admin
from django.utils.html import format_html

from .models import (
    TenantClaudeLoginSession,
    TenantClaudeRuntime,
    TenantCodexLoginSession,
    TenantCodexRuntime,
)


@admin.register(TenantClaudeRuntime)
class TenantClaudeRuntimeAdmin(admin.ModelAdmin):
    list_display = (
        "linux_user",
        "status_badge",
        "provider",
        "privacy_mode",
        "last_verified_at",
        "created_at",
    )
    list_filter = ("status", "provider", "privacy_mode")
    readonly_fields = (
        "id",
        "tenant_content_type",
        "tenant_object_id",
        "created_at",
        "updated_at",
    )
    search_fields = ("linux_user", "home_dir")
    ordering = ("-created_at",)

    def status_badge(self, obj):
        color = {
            "ready": "green",
            "login_required": "orange",
            "not_configured": "gray",
            "failed": "red",
        }.get(obj.status, "gray")
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display(),
        )
    status_badge.short_description = "Status"


@admin.register(TenantClaudeLoginSession)
class TenantClaudeLoginSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "runtime",
        "status",
        "started_at",
        "expires_at",
        "completed_at",
    )
    list_filter = ("status",)
    readonly_fields = (
        "id",
        "runtime",
        "started_at",
        "expires_at",
    )
    ordering = ("-started_at",)

    def has_add_permission(self, request):
        return False


@admin.register(TenantCodexRuntime)
class TenantCodexRuntimeAdmin(admin.ModelAdmin):
    list_display = (
        "linux_user",
        "status_badge",
        "provider",
        "auth_method",
        "privacy_mode",
        "last_verified_at",
        "created_at",
    )
    list_filter = ("status", "provider", "auth_method", "privacy_mode")
    readonly_fields = (
        "id",
        "tenant_content_type",
        "tenant_object_id",
        "created_at",
        "updated_at",
    )
    search_fields = ("linux_user", "home_dir", "provider_home_dir")
    ordering = ("-created_at",)

    def status_badge(self, obj):
        color = {
            "ready": "green",
            "login_required": "orange",
            "not_configured": "gray",
            "failed": "red",
        }.get(obj.status, "gray")
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display(),
        )
    status_badge.short_description = "Status"


@admin.register(TenantCodexLoginSession)
class TenantCodexLoginSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "runtime",
        "status",
        "started_at",
        "expires_at",
        "completed_at",
    )
    list_filter = ("status",)
    readonly_fields = (
        "id",
        "runtime",
        "started_at",
        "expires_at",
    )
    ordering = ("-started_at",)

    def has_add_permission(self, request):
        return False
