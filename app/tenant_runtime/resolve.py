# tenant_runtime/resolve.py
"""
A person's own AI runtime: find it, create it, and check it before use.

Service Trust ST-3. Every caller that runs work on a person's cloud account goes
through person_runtime(): no Group runtime, no other person's, and never the
server's own login. A missing, unready or disallowed runtime stops the work with
its own reason; nothing falls back.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction

from tenant_runtime import pool
from tenant_runtime.models import TenantClaudeRuntime, TenantCodexRuntime

CLAUDE = "claude"
CODEX = "codex"
_MODELS = {CLAUDE: TenantClaudeRuntime, CODEX: TenantCodexRuntime}

# Decision S4: a new person runtime serves every current cloud feature; each call
# still needs its own approval. Add a capability here when its caller moves to the
# person's runtime (Atrium and Catalyst join in ST-3 step 5).
PERSON_DEFAULT_MODES = [
    "shuttle_weave_interpret",
    "folio_note_tend",
    "writing.synopsis_linkedin",
]


class RuntimeUnavailable(Exception):
    """code: runtime_missing | runtime_not_ready | mode_not_allowed."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _model(provider: str):
    try:
        return _MODELS[provider]
    except KeyError as exc:
        raise ValueError(f"unknown provider {provider!r}") from exc


def _person_filter(user) -> dict:
    return {
        "tenant_content_type": ContentType.objects.get_for_model(get_user_model()),
        "tenant_object_id": user.pk,
    }


def get_person_runtime(user, provider: str = CLAUDE):
    # Unique per (tenant, provider); provider is each model's single default value.
    model = _model(provider)
    return model.objects.filter(**_person_filter(user), provider=model._meta.get_field("provider").default).first()


def person_runtime(user, capability: str, provider: str = CLAUDE):
    """The person's READY runtime, allowed for `capability`, or RuntimeUnavailable."""
    runtime = get_person_runtime(user, provider)
    if runtime is None:
        raise RuntimeUnavailable("runtime_missing")
    if runtime.status != runtime.STATUS_READY or not runtime.linux_user or not runtime.home_dir:
        raise RuntimeUnavailable("runtime_not_ready")
    if capability not in (runtime.allowed_ai_modes or []):
        raise RuntimeUnavailable("mode_not_allowed")
    return runtime


def ensure_person_runtime(user, provider: str = CLAUDE):
    """
    The person's runtime, created with a pool user if they have none.

    Raises pool.PoolError when no user can be assigned. Never touches another
    person's runtime: the lookup is by the requesting user alone.
    """
    existing = get_person_runtime(user, provider)
    if existing is not None:
        return existing
    model = _model(provider)
    other = get_person_runtime(user, CODEX if provider == CLAUDE else CLAUDE)
    for _attempt in range(3):
        linux_user, home_dir = pool.assign_user(existing_user=other.linux_user if other else None)
        try:
            with transaction.atomic():
                return model.objects.create(
                    **_person_filter(user),
                    linux_user=linux_user,
                    home_dir=home_dir,
                    status=model.STATUS_LOGIN_REQUIRED,
                    allowed_ai_modes=list(PERSON_DEFAULT_MODES),
                )
        except IntegrityError:
            # Another request took this user, or created this person's runtime first.
            existing = get_person_runtime(user, provider)
            if existing is not None:
                return existing
            if other:
                raise
    raise pool.PoolError("No room for another AI account right now. Ask an administrator.")
