# utils/shared/contenttypes.py

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache

from django.apps import apps
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist


@lru_cache(maxsize=128)
def _ct_by_natural_key(app_label: str, model: str) -> ContentType:
    return ContentType.objects.get_by_natural_key(app_label.lower(), model.lower())

@lru_cache(maxsize=128)
def _ct_for_model_label(model_label: str) -> ContentType:
    """
    model_label like 'groups.Group' or 'accounts.User'
    """
    model = apps.get_model(model_label)
    return ContentType.objects.get_for_model(model, for_concrete_model=False)

def resolve_content_type(
    raw: str | int,
    mapping: Mapping[str, str] | None = None,
) -> ContentType:
    """
    Resolve a client string/int into a ContentType.

    Accepted forms:
      - numeric id (e.g., 7 or "7")
      - dotted label "app.Model" / "app.model"
      - token (e.g., "group", "member") via settings.SPONSOR_MODELS or provided mapping

    Raises ObjectDoesNotExist / ValueError / MultipleObjectsReturned on failure.
    """
    if raw is None:
        raise ValueError("sponsor_content_type is required")

    s = str(raw).strip()
    if not s:
        raise ValueError("sponsor_content_type cannot be empty")

    # 1) numeric CT id
    if s.isdigit():
        return ContentType.objects.get(pk=int(s))

    # 2) dotted label
    if "." in s:
        app_label, model_name = s.split(".", 1)
        return _ct_by_natural_key(app_label, model_name)

    # 3) token → model label via mapping
    m = mapping or getattr(settings, "SPONSOR_MODELS", {})
    model_label = m.get(s.lower())
    if not model_label:
        raise ObjectDoesNotExist(
            f"Unknown sponsor token '{s}'. Configure it in settings.SPONSOR_MODELS "
            f"or send a dotted label like 'app.Model'."
        )
    return _ct_for_model_label(model_label)
