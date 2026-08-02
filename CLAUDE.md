# CLAUDE.md — mixtape-release-core

Django backend monolith for the Mixtape platform.

---

## ADR Status Protocol

When implementation work in this repo is governed by an ADR: read `{adr-name}-status.md` (in `../puddlejump/decisions/`) at the start of every session. Update the checkpoint table (row → ✅, commit hash) as phases complete. If no status file exists for the ADR, flag it — one should have been created at ratification.

---

## Commit Handoff

Every unit of work — including ad hoc changes — should produce a named git
commit in this repo. Commit your work files here first, then draft the inbox
entry below. Do not commit to the Puddlejump repo — Puddlejump handles its
own commits. Present the inbox draft to the CTO for approval. Do not write
to the inbox until approved.

File path: `../puddlejump/build-log-inbox/[YYYY-MM-DD]-mixtape-release-core-[short-hash].md`

---

## Internal Service Auth Conventions

Two authentication classes cover all internal service-to-service calls. Do not invent a third.

**`ServiceJWTAuthentication`** (`livewire/auth.py`) — use when the token was minted by the livewire exchange endpoint and maps to a real Django user. Current callers: `chat`, `dispatch`.

**`InternalServiceAuthentication`** (`livewire/auth.py`) — use when the caller is a service principal with no Django user identity (Switchboard, orchestration services). Returns `(AnonymousUser(), payload)`; attaches `request.auth_payload` and `request.service_principal`. Current callers: `initiatives` ActionRun endpoints.

**Scope permission classes** (`livewire/permissions.py`) — always thin one-line subclasses of `_HasServiceScope`. They read `request.auth_payload["scopes"]` only — no token extraction, no JWT decoding in the permission layer.

**Transport** — both authenticators accept `Authorization: Bearer` and `X-Service-Token`. Prefer Bearer; `X-Service-Token` is an accepted fallback for service callers that cannot easily set the Authorization header.

**New internal endpoints** — choose one of the two authenticators based on whether the call carries a user identity. No ad hoc JWT decoding inside permission classes.

*Promoted from `puddlejump/zz/_deprecated/auth-notes.md` (confirmed valid 2026-08-01).*

---

File content:

```
---
repo: mixtape-release-core
commit: [short hash] — [one-line commit message]
date: [YYYY-MM-DD]
work_effort: [ADR, build plan, or initiative name]
---

[2–4 sentences — what was implemented and why, written for someone reading
this log months from now. Name the models, endpoints, or surfaces involved.
Avoid vague summaries like "fixed some bugs."]
```
