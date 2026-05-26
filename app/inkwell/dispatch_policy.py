# inkwell/dispatch_policy.py
#
# Evaluates group dispatch_policy at step 2 of the Inkwell fan-out path.
# Called after verb + context are declared, before privacy filtering.
# Enforcement only — surfaces read GroupContext for UI state.

from dataclasses import dataclass, field
from enum import Enum


class DispatchRoute(Enum):
    CLOUD = "cloud"
    LOCAL = "local"
    CONSENT_REQUIRED = "consent_required"   # surface must prompt before cloud
    BLOCKED = "blocked"                      # cloud path unconditionally closed
    CONFIG_ERROR = "config_error"           # local model not available, cloud also blocked


@dataclass
class DispatchDecision:
    route: DispatchRoute
    reason: str
    consent_message: str = ""
    http_status: int = 200


def evaluate(
    *,
    dispatch_policy: str,
    verb_cloud_eligible: bool,
    local_model_available: bool,
    verb_id: str = "",
    local_verb_overrides: list = field(default_factory=list),
) -> DispatchDecision:
    """
    Returns a DispatchDecision for the given verb + group policy combination.

    dispatch_policy: one of cloud_default | local_preferred | local_only | local_strict
    verb_cloud_eligible: True if the Codex marks this verb cloudEligible
    local_model_available: True if the configured local model is running and healthy
    verb_id: Codex verb ID string (used to check local_verb_overrides)
    local_verb_overrides: list of verb IDs permitted behind consent gate in local_only mode
    """
    if local_verb_overrides is None:
        local_verb_overrides = []

    # Step 1 — verb not cloud-eligible: always route local regardless of policy.
    if not verb_cloud_eligible:
        if not local_model_available:
            return DispatchDecision(
                route=DispatchRoute.CONFIG_ERROR,
                reason="Local model not configured — this operation is unavailable in your current policy.",
            )
        return DispatchDecision(route=DispatchRoute.LOCAL, reason="Verb is local-only.")

    # Step 2 — evaluate policy.
    if dispatch_policy == "cloud_default":
        return DispatchDecision(route=DispatchRoute.CLOUD, reason="Standard cloud routing.")

    if dispatch_policy == "local_preferred":
        if not local_model_available:
            return DispatchDecision(
                route=DispatchRoute.CONFIG_ERROR,
                reason="Local model not configured — this operation is unavailable in your current policy.",
            )
        return DispatchDecision(
            route=DispatchRoute.CONSENT_REQUIRED,
            reason="local_preferred: cloud requires per-operation user consent.",
            consent_message="This operation performs better with cloud. Send?",
        )

    if dispatch_policy == "local_only":
        if verb_id and verb_id in local_verb_overrides:
            if not local_model_available:
                return DispatchDecision(
                    route=DispatchRoute.CONFIG_ERROR,
                    reason="Local model not configured — this operation is unavailable in your current policy.",
                )
            return DispatchDecision(
                route=DispatchRoute.CONSENT_REQUIRED,
                reason="local_only: verb is on override list; consent gate required.",
                consent_message="This will send content to a cloud model. Confirm?",
            )
        if not local_model_available:
            return DispatchDecision(
                route=DispatchRoute.CONFIG_ERROR,
                reason="Local model not configured — this operation is unavailable in your current policy.",
            )
        return DispatchDecision(route=DispatchRoute.LOCAL, reason="local_only: cloud path blocked.")

    if dispatch_policy == "local_strict":
        # Hard wall. local_verb_overrides silently ignored.
        if not local_model_available:
            return DispatchDecision(
                route=DispatchRoute.CONFIG_ERROR,
                reason="Local model not configured — this operation is unavailable in your current policy.",
            )
        return DispatchDecision(
            route=DispatchRoute.BLOCKED,
            reason="local_strict: cloud blocked unconditionally.",
            http_status=403,
        )

    # Unknown policy value — fail safe to local.
    return DispatchDecision(route=DispatchRoute.LOCAL, reason=f"Unknown policy '{dispatch_policy}'; defaulting to local.")


def enforce_local_strict(group_dispatch_policy: str) -> bool:
    """
    Returns True if the group's policy is local_strict.
    Call this at the Inkwell dispatch boundary to gate any cloud dispatch attempt
    with a 403 before routing logic runs.
    """
    return group_dispatch_policy == "local_strict"
