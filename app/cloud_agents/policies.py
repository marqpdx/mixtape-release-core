"""Provider-neutral execution policy mapping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


AgentPolicyName = Literal["read_only", "workspace_edit", "dev_agent", "audit"]
CodexSandbox = Literal["read-only", "workspace-write"]


@dataclass(frozen=True)
class AgentExecutionPolicy:
    name: AgentPolicyName = "read_only"
    codex_sandbox: CodexSandbox = "read-only"
    allow_writes: bool = False


READ_ONLY_POLICY = AgentExecutionPolicy("read_only", "read-only", False)
WORKSPACE_EDIT_POLICY = AgentExecutionPolicy("workspace_edit", "workspace-write", True)
DEV_AGENT_POLICY = AgentExecutionPolicy("dev_agent", "workspace-write", True)
AUDIT_POLICY = AgentExecutionPolicy("audit", "read-only", False)

POLICIES: dict[str, AgentExecutionPolicy] = {
    p.name: p
    for p in (
        READ_ONLY_POLICY,
        WORKSPACE_EDIT_POLICY,
        DEV_AGENT_POLICY,
        AUDIT_POLICY,
    )
}


def resolve_policy(policy: str | AgentExecutionPolicy | None) -> AgentExecutionPolicy:
    if isinstance(policy, AgentExecutionPolicy):
        return policy
    if not policy:
        return READ_ONLY_POLICY
    return POLICIES.get(policy, READ_ONLY_POLICY)

