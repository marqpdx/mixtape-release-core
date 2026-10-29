# tenant_runtime/pool.py
"""
Linux users for person runtimes (Service Trust ST-3, decision S1).

Core never creates Linux users. An operator creates a small pool ahead of time,
as members of RUNTIME_POOL_GROUP (default "mixtape-runtimes"), each with a
nologin shell and a private home. When a person connects an AI account, core
assigns them a free pool user; the person never sees it.

A person keeps one Linux user for every provider (decision S2): their Codex
runtime reuses their Claude runtime's user, and the reverse.

Reading /etc/passwd and /etc/group needs no privilege.
"""

from __future__ import annotations

import grp
import logging
import pwd
from collections.abc import Iterable

from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_POOL_GROUP = "mixtape-runtimes"
# A runtime user in any of these could read the release tree, the server's own
# secrets, or act as an administrator. Such a user is never assigned.
FORBIDDEN_GROUPS = frozenset({"mixtape", "crossroads", "sudo", "admin", "wheel", "root", "docker"})


class PoolError(Exception):
    """No runtime user can be assigned; the message is safe to show the person."""


def pool_group() -> str:
    return getattr(settings, "RUNTIME_POOL_GROUP", "") or DEFAULT_POOL_GROUP


def _groups_of(username: str) -> set[str]:
    names = {g.gr_name for g in grp.getgrall() if username in g.gr_mem}
    try:
        names.add(grp.getgrgid(pwd.getpwnam(username).pw_gid).gr_name)
    except KeyError:
        pass
    return names


def pool_members() -> list[str]:
    """Users in the pool group, in a stable order. Empty if the group doesn't exist."""
    try:
        return sorted(grp.getgrnam(pool_group()).gr_mem)
    except KeyError:
        return []


def pick_free_user(candidates: Iterable[str], in_use: set[str], groups_of=_groups_of) -> str | None:
    """The first candidate not already assigned and in no forbidden group."""
    for name in candidates:
        if name in in_use:
            continue
        bad = groups_of(name) & FORBIDDEN_GROUPS
        if bad:
            logger.error("[runtime-pool] %s is in %s; never assigned", name, ", ".join(sorted(bad)))
            continue
        return name
    return None


def users_in_use() -> set[str]:
    from tenant_runtime.models import TenantClaudeRuntime, TenantCodexRuntime

    used = set(TenantClaudeRuntime.objects.exclude(linux_user="").values_list("linux_user", flat=True))
    used |= set(TenantCodexRuntime.objects.exclude(linux_user="").values_list("linux_user", flat=True))
    return used


def home_of(username: str) -> str:
    return pwd.getpwnam(username).pw_dir


def assign_user(existing_user: str | None = None) -> tuple[str, str]:
    """
    Return (linux_user, home_dir) for a person's new runtime.

    existing_user: the Linux user the person already has for another provider (S2);
    reused after checking it is still a safe pool member.
    """
    members = pool_members()
    if existing_user:
        if existing_user in members and not (_groups_of(existing_user) & FORBIDDEN_GROUPS):
            return existing_user, home_of(existing_user)
        raise PoolError("Your existing AI account user is no longer available. Ask an administrator.")
    if not members:
        raise PoolError("AI accounts aren't set up on this server yet.")
    name = pick_free_user(members, users_in_use())
    if not name:
        raise PoolError("No room for another AI account right now. Ask an administrator.")
    return name, home_of(name)
