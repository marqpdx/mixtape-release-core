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


def run_as_argv(linux_user: str | None, argv: list[str]) -> list[str]:
    """
    Prefix argv so it runs as a runtime's Linux user.

    Workers run unprivileged (systemd User=crossroads), so `runuser` (root only)
    cannot work. A narrow sudo rule allows exactly the provider CLIs, as members of
    the runtime group only (Service Trust ST-3, decision S1):

        crossroads ALL=(%mixtape-runtimes) NOPASSWD: /usr/local/bin/claude, /usr/local/bin/codex

    -n never prompts; -H sets HOME from the target user's passwd entry, so each CLI
    finds its own login under that home. sudo resets the environment: provider keys
    never reach the CLI, and provider home variables (CODEX_HOME) fall back to the
    CLI's default under HOME.
    """
    if not linux_user:
        return argv
    return ["sudo", "-n", "-H", "-u", linux_user, "--", *argv]

