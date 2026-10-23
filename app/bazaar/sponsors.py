# bazaar/sponsors.py
#
# Resolve a Bazaar sponsor token ("user" or "group") to its ContentType through
# the platform's shared resolver and settings.SPONSOR_MODELS. Bazaar's API names
# a member sponsor "user"; the platform token is "member", so both are accepted.
# A bare ContentType lookup by model name found no "user" model (the user model is
# users.CustomUser) and two "group" models (auth.Group, groups.Group).

from django.conf import settings

from utils.shared.contenttypes import resolve_content_type

BAZAAR_SPONSOR_MODELS = {
    **getattr(settings, "SPONSOR_MODELS", {}),
    "user": settings.AUTH_USER_MODEL,
}


def sponsor_content_type(token):
    """Return the ContentType for a sponsor token; raises ObjectDoesNotExist or ValueError."""
    return resolve_content_type(token, mapping=BAZAAR_SPONSOR_MODELS)
