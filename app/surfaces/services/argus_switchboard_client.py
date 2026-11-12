# surfaces/services/argus_switchboard_client.py
#
# Core -> Cass's Switchboard client for the two argus.* tools (ADR-0064
# AC-5a; zz/_handoffs/handoff-2026-11-11-blue-ac5-client-and-dispatch.md).
# Switches on only once both ARGUS_SWITCHBOARD_URL (AC-3's tunnel) and
# ARGUS_RUN_JWT_SECRET exist; until then every call degrades to
# NotReachable without attempting a connection -- no fallback to any other
# host or secret.
#
# Mints a fresh token per call via mint_argus_run_token() (its own secret,
# short TTL, so caching it buys nothing). Sends it as `Authorization:
# Bearer`, not a custom header: Switchboard's own verifier
# (mixtape-release-switchboard, app/services/argus_run_auth.py,
# require_argus_run_token) requires that scheme specifically, and it's the
# convention this repo's CLAUDE.md already prefers for incoming calls --
# deliberately not copying stackroom_client's/agent_research's
# X-Service-Token convention, which is for a different direction and a
# different verifier that doesn't require Bearer.
#
# Not a general-purpose service client: reuses mint_argus_run_token() and
# the requests/timeout/error-mapping shape already established by
# stackroom_client.py and initiatives.services.agent_research, rather than
# inventing a third authenticator or a third HTTP-client shape
# (CLAUDE.md, Internal Service Auth Conventions).

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests
from django.conf import settings

from surfaces.services.argus_run_auth import ArgusRunAuthError, mint_argus_run_token

# Short on both ends: this is a synchronous call inside a request/task path,
# and ARGUS_RUN_JWT_TTL_SECONDS (120s default) already bounds how long any
# single token is good for.
_CONNECT_TIMEOUT_SECONDS = 5
_READ_TIMEOUT_SECONDS = 15


class ArgusSwitchboardError(RuntimeError):
    """A validation 4xx from Switchboard's own request checking -- the
    caller's request was malformed, not a reachability problem. Distinct
    from NotReachable, which covers everything that isn't the caller's
    fault (unset config, network failure, timeout, 5xx, or an auth
    rejection that likely means misconfiguration on one side or the
    other, not a bad request)."""

    def __init__(self, detail: str, *, status_code: int, body: str = ""):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.body = body


@dataclass(frozen=True)
class NotReachable:
    reason: str


def _base_url() -> str | None:
    url = getattr(settings, "ARGUS_SWITCHBOARD_URL", None)
    return url.rstrip("/") if url else None


def _default_tenant() -> dict[str, str]:
    # Same platform-default tenant settings used elsewhere for an outbound
    # call with no per-request tenant of its own (SWITCHBOARD_DEFAULT_TENANT_ID/
    # _NAMESPACE, app/mixtape/settings/base.py) -- not request.user.pk, which
    # is what ActionRun.tenant_id uses for a different purpose (recording
    # whose action this was), not what identifies a Switchboard tenant.
    return {
        "id": str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", "00000000-0000-0000-0000-000000000001")),
        "namespace": str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", "platform:crossroads")),
    }


def _actor(actor_user_id: str | None) -> dict[str, str] | None:
    return {"user_id": actor_user_id} if actor_user_id else None


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any] | NotReachable:
    base_url = _base_url()
    if base_url is None:
        return NotReachable("ARGUS_SWITCHBOARD_URL is not configured (AC-3 pending).")

    try:
        token = mint_argus_run_token()
    except ArgusRunAuthError as exc:
        return NotReachable(str(exc))

    try:
        response = requests.post(
            f"{base_url}{path}",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=(_CONNECT_TIMEOUT_SECONDS, _READ_TIMEOUT_SECONDS),
        )
    except requests.exceptions.Timeout as exc:
        return NotReachable(f"Switchboard timed out: {exc}")
    except requests.RequestException as exc:
        return NotReachable(f"Switchboard unreachable: {exc}")

    if response.status_code in (401, 403):
        return NotReachable(f"Switchboard rejected the argus run token ({response.status_code}).")
    if response.status_code >= 500:
        return NotReachable(f"Switchboard error {response.status_code}: {response.text}")
    if response.status_code >= 400:
        raise ArgusSwitchboardError(
            f"Switchboard rejected the request ({response.status_code}).",
            status_code=response.status_code,
            body=response.text,
        )

    return response.json()


def list_blocks(*, actor_user_id: str | None = None) -> dict[str, Any] | NotReachable:
    payload = {"tenant": _default_tenant(), "actor": _actor(actor_user_id), "payload": {}}
    return _post("/tools/argus/list_blocks", payload)


def start_run(
    *,
    block_slug: str,
    run_series_id: str | None = None,
    per_turn_caps: dict | None = None,
    actor_user_id: str | None = None,
) -> dict[str, Any] | NotReachable:
    payload = {
        "tenant": _default_tenant(),
        "actor": _actor(actor_user_id),
        "payload": {
            "block_slug": block_slug,
            "run_series_id": run_series_id,
            "per_turn_caps": per_turn_caps or {},
        },
    }
    return _post("/tools/argus/start_run", payload)
