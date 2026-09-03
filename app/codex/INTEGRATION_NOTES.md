# OpenAI Codex Integration Notes

Date: 2026-09-03

## Current CLI Evidence

Installed CLI:

```text
codex-cli 0.153.0
```

Confirmed commands:

- `codex login --device-auth`
- `codex login status`
- `codex logout`
- `codex exec --json`
- `codex exec resume --json`

Current `codex exec --json` emits JSONL events including:

- `thread.started` with `thread_id`
- `turn.started`
- `item.completed` with `item.type == "agent_message"`
- `turn.completed` with `usage`

Local smoke command:

```bash
codex exec --json --ephemeral --sandbox read-only --skip-git-repo-check --cd /tmp "Reply exactly: OK"
```

Observed redacted shape:

```jsonl
{"type":"thread.started","thread_id":"..."}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"OK"}}
{"type":"turn.completed","usage":{"input_tokens":14268,"cached_input_tokens":4480,"cache_write_input_tokens":0,"output_tokens":5,"reasoning_output_tokens":0}}
```

`codex login status -c 'cli_auth_credentials_store="file"'` reported:

```text
Logged in using ChatGPT
```

## Architecture

The MVP keeps provider-specific code narrow while adding shared primitives:

- `cloud_agents.constants` owns provider identifiers.
- `cloud_agents.policies` owns Mixtape execution policy names and Codex sandbox mapping.
- `cloud_agents.subprocess` owns per-Linux-user environment and `runuser` argv helpers.
- `cloud_agents.events` owns normalized SSE encoding.
- `codex.service` owns Codex CLI argv construction, JSONL parsing, blocking execution, streaming execution, auth status, logout, and process termination.

Atrium now separates:

- `AtriumSession`: human-visible conversation and selected `ai_provider`.
- `CloudAgentSession`: provider-native mapping for session id, Linux user, working directory, policy, and lifecycle state.

This leaves room for Claude Code, Codex, Gemini, and local LLM tooling to share the same Mixtape concepts without forcing all providers into identical process models.

## Security Notes

Codex invocations set:

- `HOME=<tenant home>`
- `CODEX_HOME=<tenant home>/.codex` unless overridden by runtime metadata
- `PATH=/usr/local/bin:/usr/bin:/bin`
- `cli_auth_credentials_store="file"`

Provider API-key/access-token environment variables are stripped by default so ChatGPT-backed Codex use does not silently fall back to shared API billing.

The MVP Codex Atrium path is read-only by default via `--sandbox read-only`. Initial `codex exec` supports explicit `--cd`; current `codex exec resume` help does not expose `--cd` or `--sandbox`, so resume relies on Codex's persisted thread context plus subprocess `cwd`.

Provider credentials are not stored in Django. `TenantCodexRuntime` and `TenantCodexLoginSession` store non-secret operational metadata, login URL/code, state, and timestamps only.

## Remaining Gaps

The full disposable Linux-user proof is still required before client rollout:

1. Create/select a disposable Linux user.
2. Run `codex login --device-auth` through `runuser`.
3. Complete login with a dedicated test OpenAI account.
4. Verify `CODEX_HOME/auth.json` ownership and permissions.
5. Run `codex exec --json`.
6. Run `codex exec resume <thread_id> --json`.
7. Verify logout and auth-expiry behavior.
8. Confirm tenant A cannot read tenant B's Codex home or workspace.

Usage-limit and auth-expiry JSON/error shapes still need real-world samples.
