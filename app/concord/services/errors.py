"""Explicit denials for Concord's local-only model services."""


class CloudAIDisabledError(RuntimeError):
    """Direct cloud AI was requested outside a gated Switchboard capability."""

    code = "cloud_ai_disabled"
