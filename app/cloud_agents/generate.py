"""The thin shared core behind a cloud-dispatched step (Heddle CR-01,
puddlejump decisions/heddle-adr/heddle-cr-01-cloud-generation-core.md):
resolve the person's own runtime for a named capability, run one
stateless, tool-less prompt on it, and parse its JSON output.

This is deliberately narrow. Everything that makes a cloud step *that
surface's own* -- Heddle's parent/child ActionRun weave and its approval
payload matching a source digest and revision; Ariadne's per-Inquiry
consent event logged against each of its per-theme calls -- stays with
the caller. So does validating the parsed result's *shape*: a Heddle
Reading's Contour Shape and span rules are nothing like Ariadne's claims
schema, and inventing one generic validator for both would be exactly the
speculative shared infrastructure Spike Reconnaissance warns against. This
module only does the part genuinely common to both: resolve, dispatch,
parse.

Second real consumer, not a speculative first one: Heddle's own
`run_cloud_interpretation` (heddle/tasks.py) already ran this sequence
inline; Ariadne's Inquiry Draft needed it next, live, and a third
pipeline sending shaped prompt/schema packets to a cloud agent is the
general case this CR names, not a one-off.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from tenant_runtime.resolve import person_runtime as resolve_person_runtime


@dataclass
class CloudGenerationResult:
    runtime: object
    parsed: dict | None
    failure: Literal["auth_failure", "timeout", "error", "empty", "invalid_json"] | None
    usage: dict | None
    elapsed_ms: int | None


def generate(
    *, author, capability: str, prompt: str, provider: str = "claude", timeout: int = 180,
) -> CloudGenerationResult:
    """Resolve `author`'s own runtime (raises `tenant_runtime.resolve.RuntimeUnavailable`
    if it's missing, not ready, or doesn't allow `capability` -- the caller's own
    problem to translate, exactly as it already did when this check lived inline),
    then run `prompt` with no tools and parse its JSON output. Execution and
    parsing failures are returned on the result (`.failure`), not raised, so a
    caller can still act on the resolved runtime afterward (Heddle's
    `verify_claude_runtime` on an auth failure needs it)."""
    from claude.service import run_blocking

    runtime = resolve_person_runtime(author, capability, provider)
    result = run_blocking(
        prompt,
        run_as_user=runtime.linux_user,
        home_dir=runtime.home_dir,
        tools="",
        timeout=timeout,
        log_context={"capability": capability},
    )
    if result.failure:
        return CloudGenerationResult(
            runtime=runtime, parsed=None, failure=result.failure, usage=result.usage, elapsed_ms=result.elapsed_ms,
        )
    try:
        parsed = json.loads(result.output or "")
    except json.JSONDecodeError:
        return CloudGenerationResult(
            runtime=runtime, parsed=None, failure="invalid_json", usage=result.usage, elapsed_ms=result.elapsed_ms,
        )
    return CloudGenerationResult(
        runtime=runtime, parsed=parsed, failure=None, usage=result.usage, elapsed_ms=result.elapsed_ms,
    )
