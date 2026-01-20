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
