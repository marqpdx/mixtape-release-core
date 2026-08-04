"""
Tenant context management for request-scoped tenant isolation.

Uses contextvars.ContextVar for ASGI compatibility — threading.local is not
safe under async because a single OS thread handles multiple coroutines.
The ContextVar is isolated per coroutine (per request) automatically.
"""
from __future__ import annotations

import contextvars
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from groups.models.group import Group

_tenant_var: contextvars.ContextVar["Group | None"] = contextvars.ContextVar(
    "current_tenant", default=None
)


def get_current_tenant() -> "Group | None":
    return _tenant_var.get()


def set_current_tenant(group: "Group | None") -> contextvars.Token:
    return _tenant_var.set(group)


def clear_current_tenant(token: contextvars.Token) -> None:
    _tenant_var.reset(token)
