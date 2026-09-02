# app/mixtape/tenant_urls.py

from django.conf import settings

_DEFAULT_CATALYST_URL_TEMPLATE = (
    "https://{slug}.apps.crossroads.place/app/groups/{slug}/catalyst"
)


def get_catalyst_workspace_url(slug: str) -> str:
    """Return the canonical Catalyst workspace URL for a tenant slug."""
    template = getattr(settings, "CATALYST_TENANT_URL_TEMPLATE", _DEFAULT_CATALYST_URL_TEMPLATE)
    return template.format(slug=slug)
