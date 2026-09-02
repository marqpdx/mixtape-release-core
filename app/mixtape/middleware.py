# app/mixtape/middleware.py


"""
TenantMiddleware — resolves the request-scoped tenant from subdomain or header.

Resolution order:
  1. X-Tenant-Slug header — accepted only in DEBUG mode or from TENANT_HEADER_TRUSTED_IPS.
     Production edge infrastructure must strip this header from external traffic
     before it reaches the app. (FN-D2)
  2. Subdomain — {slug}.apps.crossroads.place resolves to Group(slug=slug, is_active=True).
     Only fires when the host ends with TENANT_SUBDOMAIN_SUFFIX; platform subdomains
     (api, www, chat) are never tested against the Group table.

Missing tenant is not an error at middleware level — request.tenant is set to None.
Views that require a tenant apply TenantContextRequired (mixtape/permissions.py),
which returns HTTP 428 if tenant is absent. Global routes (admin, health checks,
beat tasks) expect None and must not use TenantContextRequired.
"""
from __future__ import annotations

from django.conf import settings

from mixtape.tenant import clear_current_tenant, set_current_tenant


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant = self._resolve(request)
        request.tenant = tenant
        token = set_current_tenant(tenant)
        try:
            response = self.get_response(request)
        finally:
            clear_current_tenant(token)
        return response

    def _resolve(self, request):
        from groups.models.group import Group

        # Header override — internal/dev only
        header_slug = request.META.get("HTTP_X_TENANT_SLUG")
        if header_slug and self._header_allowed(request):
            return Group.objects.filter(slug=header_slug, is_active=True).first()

        # Subdomain resolution — canonical for production
        suffix = getattr(settings, "TENANT_SUBDOMAIN_SUFFIX", "")
        host = request.get_host().split(":")[0]
        if suffix and host.endswith(suffix):
            slug = host[: -len(suffix)]
            if slug:
                return Group.objects.filter(slug=slug, is_active=True).first()

        return None

    def _header_allowed(self, request) -> bool:
        if getattr(settings, "DEBUG", False):
            return True
        trusted = getattr(settings, "TENANT_HEADER_TRUSTED_IPS", [])
        return request.META.get("REMOTE_ADDR") in trusted
