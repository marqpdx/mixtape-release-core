from django.contrib import admin

from ops.models import BuildLogEntry, OpsAuditLog, OpsCheckResult, OpsIncidentSnapshot, OpsSnapshot


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


@admin.register(BuildLogEntry)
class BuildLogEntryAdmin(admin.ModelAdmin):
    list_display = ("date", "repo", "commit_hash", "work_effort", "ingested_at")
    list_filter = ("repo", "date")
    search_fields = ("commit_hash", "commit_message", "work_effort", "body")
    ordering = ("-date",)
    readonly_fields = (
        "commit_hash",
        "commit_message",
        "repo",
        "date",
        "work_effort",
        "body",
        "source_filename",
        "ingested_at",
    )

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
