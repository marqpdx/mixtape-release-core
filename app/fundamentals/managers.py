"""
Tenant-scoped queryset and manager for BaseContent subclasses.

BaseContent provides the sponsor FK fields that make scoping possible.
Scoping is opt-in per model — not automatic on every BaseContent subclass.
Group is explicitly excluded from this manager (FN-D4).

Usage in views and tasks (Phase 1 — explicit calls, no default manager changes):
    WritingPiece.objects.for_tenant(group)
    WritingPiece.objects.for_current_tenant(strict=True)

Usage after Phase 2 opt-in (model-by-model, after semantics verified):
    class SomeModel(BaseContent):
        objects = TenantManager()
        _unscoped_manager = models.Manager()
"""
from django.contrib.contenttypes.models import ContentType
from django.db import models


class MissingTenantContextError(Exception):
    pass


class TenantScopedQuerySet(models.QuerySet):

    def for_tenant(self, group):
        """Filter to records sponsored by the given Group."""
        ct = ContentType.objects.get_for_model(group)
        return self.filter(
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )

    def for_current_tenant(self, strict: bool = False):
        """
        Filter to the tenant currently in request context.

        strict=True raises MissingTenantContextError if no tenant is set —
        use this in views where a missing tenant indicates a code error.
        strict=False (default) returns the unscoped queryset when no tenant is
        set — use this in contexts where cross-tenant access is expected
        (admin, management commands, beat tasks).
        """
        from mixtape.tenant import get_current_tenant
        tenant = get_current_tenant()
        if tenant is None:
            if strict:
                raise MissingTenantContextError(
                    "for_current_tenant(strict=True) called with no tenant in context. "
                    "Ensure TenantMiddleware is active and the request carries a resolved tenant."
                )
            return self
        return self.for_tenant(tenant)


class TenantManager(models.Manager):
    """
    Drop-in replacement for models.Manager on opt-in tenant-scoped models.
    Provides .for_tenant() and .for_current_tenant() on the default manager.
    """

    def get_queryset(self):
        return TenantScopedQuerySet(self.model, using=self._db)

    def for_tenant(self, group):
        return self.get_queryset().for_tenant(group)

    def for_current_tenant(self, strict: bool = False):
        return self.get_queryset().for_current_tenant(strict=strict)
