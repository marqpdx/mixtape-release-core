"""Shared subprocess helpers for per-Linux-user provider execution."""

from __future__ import annotations

import os

DEFAULT_AGENT_PATH = "/usr/local/bin:/usr/bin:/bin"

_PROVIDER_SECRET_ENV = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_API_KEY_HELPER",
    "OPENAI_API_KEY",
    "OPENAI_API_KEY_PATH",
    "CODEX_ACCESS_TOKEN",
)


def provider_env(
    *,
    home_dir: str | None = None,
    provider_home_var: str | None = None,
    provider_home_dir: str | None = None,
    strip_provider_secrets: bool = True,
) -> dict:
    """Build a narrow provider subprocess environment."""
    env = os.environ.copy()
    if strip_provider_secrets:
        for key in _PROVIDER_SECRET_ENV:
            env.pop(key, None)
    env["PATH"] = DEFAULT_AGENT_PATH
    if home_dir:
        env["HOME"] = home_dir
    if provider_home_var and provider_home_dir:
        env[provider_home_var] = provider_home_dir
    return env


def runuser_argv(linux_user: str | None, argv: list[str]) -> list[str]:
    """Prefix argv with runuser when a tenant Linux identity is supplied."""
    if not linux_user:
        return argv
    return ["runuser", "-u", linux_user, "--", *argv]

