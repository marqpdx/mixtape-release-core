from django.contrib import admin

from .models import ImpersonationAuditLog


@admin.register(ImpersonationAuditLog)
class ImpersonationAuditLogAdmin(admin.ModelAdmin):
    list_display = ("actor", "target", "started_at", "ended_at", "ip_address")
    list_filter = ("started_at",)
    readonly_fields = ("actor", "target", "started_at", "ended_at", "ip_address", "session_key")
    ordering = ("-started_at",)
