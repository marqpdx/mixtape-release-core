from django.conf import settings
from django.db import models


class OpsCheckResult(models.Model):
    check_name = models.CharField(max_length=128, db_index=True)
    status = models.CharField(max_length=16)
    value_json = models.JSONField(default=dict, blank=True)
    latency_ms = models.IntegerField(null=True, blank=True)
    ran_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-ran_at"]


class OpsIncidentSnapshot(models.Model):
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ops_incident_snapshots",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    snapshot_json = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]


class OpsSnapshot(models.Model):
    SOURCE_SCHEDULED = "scheduled"
    SOURCE_MANUAL = "manual"
    SOURCE_CHOICES = [
        (SOURCE_SCHEDULED, "Scheduled"),
        (SOURCE_MANUAL, "Manual"),
    ]

    server_name = models.CharField(max_length=64, db_index=True)
    subsystem = models.CharField(max_length=64, db_index=True)
    status = models.CharField(max_length=16, default="unavailable")
    collected_at = models.DateTimeField(db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    collector_version = models.CharField(max_length=32, default="1.0")
    data = models.JSONField(default=dict, blank=True)
    errors = models.JSONField(default=list, blank=True)
    latency_ms = models.IntegerField(null=True, blank=True)
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default=SOURCE_SCHEDULED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-collected_at", "-updated_at"]
        indexes = [
            models.Index(
                fields=["server_name", "subsystem", "-collected_at"],
                name="ops_snap_srv_subsys_idx",
            ),
        ]


class OpsAuditLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ops_audit_logs",
    )
    action = models.CharField(max_length=128)
    target = models.CharField(max_length=256, blank=True, default="")
    params_json = models.JSONField(default=dict, blank=True)
    result = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
