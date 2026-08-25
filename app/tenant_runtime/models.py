# tenant_runtime/models.py
import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class TenantClaudeRuntime(models.Model):
    """
    Non-secret runtime metadata for a tenant's per-user Claude Code subprocess.

    The credential truth lives in ~/.claude/ in the tenant's Linux home directory —
    nothing secret is stored here. This record tracks operational state only.

    Tenant is polymorphic (currently always a Group, but wired to accept any model
    so Atrium and other surfaces can share this layer without structural changes).
    """

    STATUS_NOT_CONFIGURED = "not_configured"
    STATUS_LOGIN_REQUIRED = "login_required"
    STATUS_READY = "ready"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_NOT_CONFIGURED, "Not configured"),
        (STATUS_LOGIN_REQUIRED, "Login required"),
        (STATUS_READY, "Ready"),
        (STATUS_FAILED, "Failed"),
    ]

    PRIVACY_LOCAL_ONLY = "local_only"
    PRIVACY_ESCALATION_ALLOWED = "escalation_allowed"
    PRIVACY_CHOICES = [
        (PRIVACY_LOCAL_ONLY, "Local only"),
        (PRIVACY_ESCALATION_ALLOWED, "Escalation allowed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Polymorphic tenant — currently always groups.Group, wired generically
    # so Atrium / other surfaces can reuse this layer without schema changes.
    tenant_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="+",
    )
    tenant_object_id = models.UUIDField()
    tenant = GenericForeignKey("tenant_content_type", "tenant_object_id")

    provider = models.CharField(
        max_length=64,
        default="anthropic-claude-code",
        help_text="AI runtime provider identifier.",
    )
    linux_user = models.CharField(
        max_length=64,
        help_text="Linux username under which Claude subprocesses run (e.g. tob-catalyst).",
    )
    home_dir = models.CharField(
        max_length=256,
        help_text="Absolute home directory for linux_user (e.g. /home/tob-catalyst).",
    )
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_NOT_CONFIGURED,
        db_index=True,
    )
    privacy_mode = models.CharField(
        max_length=32,
        choices=PRIVACY_CHOICES,
        default=PRIVACY_LOCAL_ONLY,
    )
    allowed_ai_modes = models.JSONField(
        default=list,
        help_text='Permitted AI operation types for this tenant, e.g. ["extraction", "shaping"].',
    )
    last_verified_at = models.DateTimeField(null=True, blank=True)
    last_verification_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Tenant Claude Runtime"
        verbose_name_plural = "Tenant Claude Runtimes"

    def __str__(self):
        return f"{self.linux_user} [{self.status}]"

    def tenant_slug(self) -> str | None:
        """Return the tenant's slug if the tenant model exposes one."""
        obj = self.tenant
        return getattr(obj, "slug", None)


class TenantClaudeLoginSession(models.Model):
    """
    Tracks one interactive login subprocess for a TenantClaudeRuntime.

    claude auth login on a headless VPS prints its URL to stdout; the backend
    reads that URL, stores it here, and polls subprocess exit to detect completion.
    No OAuth token or credential is stored — credential truth stays in ~/.claude/.
    """

    STATUS_STARTING = "starting"
    STATUS_AWAITING_AUTH = "awaiting_auth"
    STATUS_COMPLETE = "complete"
    STATUS_FAILED = "failed"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = [
        (STATUS_STARTING, "Starting"),
        (STATUS_AWAITING_AUTH, "Awaiting auth"),
        (STATUS_COMPLETE, "Complete"),
        (STATUS_FAILED, "Failed"),
        (STATUS_EXPIRED, "Expired"),
    ]

    LOGIN_TTL_SECONDS = 600  # 10 minutes

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    runtime = models.ForeignKey(
        TenantClaudeRuntime,
        on_delete=models.CASCADE,
        related_name="login_sessions",
    )
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_STARTING,
        db_index=True,
    )
    login_url = models.TextField(
        blank=True,
        default="",
        help_text="Login URL extracted from subprocess stdout — displayed to admin, never secret.",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-started_at"]
        verbose_name = "Tenant Claude Login Session"
        verbose_name_plural = "Tenant Claude Login Sessions"

    def __str__(self):
        return f"LoginSession {self.id} [{self.status}] for {self.runtime}"

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timezone.timedelta(seconds=self.LOGIN_TTL_SECONDS)
        super().save(*args, **kwargs)

    @property
    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at
