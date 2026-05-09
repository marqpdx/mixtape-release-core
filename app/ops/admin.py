from django.contrib import admin

from ops.models import OpsAuditLog, OpsCheckResult, OpsIncidentSnapshot, OpsSnapshot


@admin.register(OpsSnapshot)
class OpsSnapshotAdmin(admin.ModelAdmin):
    list_display = ("server_name", "subsystem", "status", "source", "collected_at", "expires_at")
    list_filter = ("server_name", "subsystem", "status", "source")
    search_fields = ("server_name", "subsystem")
    ordering = ("-collected_at",)


@admin.register(OpsCheckResult)
class OpsCheckResultAdmin(admin.ModelAdmin):
    list_display = ("check_name", "status", "latency_ms", "ran_at")
    list_filter = ("status", "check_name")
    search_fields = ("check_name",)
    ordering = ("-ran_at",)


@admin.register(OpsIncidentSnapshot)
class OpsIncidentSnapshotAdmin(admin.ModelAdmin):
    list_display = ("id", "created_by", "created_at")
    ordering = ("-created_at",)


@admin.register(OpsAuditLog)
class OpsAuditLogAdmin(admin.ModelAdmin):
    list_display = ("action", "target", "result", "actor", "created_at")
    list_filter = ("result", "action")
    search_fields = ("action", "target")
    ordering = ("-created_at",)
