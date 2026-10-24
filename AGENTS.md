# AGENTS.md - Repository Root

Purpose: conservative operating guide for agents working in this Django repository.

## Priority and Scope
- This file applies repository-wide unless a deeper `AGENTS.md` exists in a subdirectory.
- More specific `AGENTS.md` files take precedence for files in their subtree.
- Keep changes scoped to the user request; avoid unrelated cleanup.

## Conservative Defaults
- Ask for confirmation before editing files.
- Ask for confirmation before running state-changing commands (tests, builds, installs, formatters, generators, migrations).
- Prefer read-only investigation first (list files, inspect configs, review existing patterns).
- Do not use network access unless explicitly approved for that command.
- Do not run destructive commands (`rm -rf`, `git reset --hard`, `git clean -fd`, force pushes) unless explicitly requested.
- Do not create commits, tags, or branches unless explicitly requested.

## Meridian Code Intelligence Discipline

> **Not built yet (2026-10-20).** None of the Meridian tools below exist: CodeGraph and OpenWiki are not installed (Meridian M-1 to M-11 pending), and Switchboard has no MCP surface. Until Meridian's status file (`puddlejump/decisions/meridian-adr/meridian-status.md`) shows them live, skip the Meridian lookup and session-start calls and read files directly. Agent instructions name only tools that exist.

Meridian is Mixtape's shared code intelligence layer, exposed through Switchboard MCP.

- Meridian/Wiki provides narrative explanations of files and modules.
- Meridian/Index provides symbol graphs, call edges, import maps, route bindings, model surfaces, and test relationships.

Use Meridian for orientation before falling back to direct file reads or text search.

### Lookup Priority
1. Meridian/Wiki: understand what a file or module means.
2. Meridian/Index: understand symbols, routes, models, dependencies, and blast radius.
3. Direct file reads: inspect implementation details only after Meridian orientation.
4. `rg` / file search: use only when Meridian has no result or the target is not a symbol.

### Session Start
At the beginning of a new session in this repo, run:

1. `repo_overview(scope?)`
2. `query_governing_docs(area)`

Use `repo_overview` to establish the current module map and repo structure.
Use `query_governing_docs` to identify ADRs, specs, and project rules that govern the work area.

If the work area is unclear, start with the broadest reasonable area, then narrow once the task is understood.

### Before Reading Unfamiliar Files
- Use `explain_file(path)` for a file-level narrative before reading an unfamiliar file.
- Use `explain_module(app_name)` before working in an unfamiliar app or package.

Read the file only when Meridian's summary is insufficient for the implementation question being answered.

### Before Using Search Tools
Before using `rg`, `grep`, `glob`, `find`, or broad file search, prefer Meridian structural lookup:

- Use `find_symbol(name, repo?)` before searching for a class, function, constant, command, setting, or management command.
- Use `find_callers(symbol, repo?)` before manually tracing who calls something.
- Use `find_callees(symbol, repo?)` before manually tracing dependencies.
- Use `trace_model(model_name)` before reading a model and its related surface.
- Use `trace_endpoint(route)` before working on an API endpoint or route.
- Use `related_files(path)` before manually following imports.
- Use `search_code_semantic(query)` when the desired behavior is known but the location is not.

Use text search only when Meridian returns no useful result, the target is not a symbol, or the task requires an exact string, literal, error message, config key, migration identifier, or copy string.

### Before Writing Code
Before changing code, establish context and blast radius:

1. `related_files(path)` - identify connected files and dependencies.
2. `related_tests(path_or_symbol)` - identify existing relevant tests.
3. `summarize_changed_files(base, head)` - understand branch changes before building on top of them.

Prefer small, targeted edits that follow existing Django project patterns. Do not introduce new architecture when an existing pattern already fits.

### Trust and Staleness Rules
- Trust Meridian for orientation. It is the shared, VPS-hosted index used by agents and refreshed regularly.
- If a Meridian result includes `is_stale: true`, state that the result is stale, use it only as orientation, and fall back to direct file reads for that specific query.
- If Meridian conflicts with direct file contents, surface the discrepancy. Use the file as the implementation source of truth for the immediate edit and treat the discrepancy as documentation/index drift.
- Fall back to file reads for implementation specifics, not for orientation.

### Available Meridian Tools

| Tool | When to use |
|------|-------------|
| `repo_overview(scope?)` | Session start; establish repo/module structure |
| `query_governing_docs(area)` | Session start; identify ADRs/specs/rules for the work area |
| `explain_file(path)` | Before reading an unfamiliar file |
| `explain_module(app_name)` | Before working in an unfamiliar app or package |
| `find_symbol(name, repo?)` | Before text search for a class, function, constant, command, or setting |
| `find_callers(symbol, repo?)` | Before tracing who calls a symbol |
| `find_callees(symbol, repo?)` | Before tracing what a symbol depends on |
| `trace_model(model_name)` | Before reading a model and its related surface |
| `trace_endpoint(route)` | Before working on an API endpoint or route |
| `related_files(path)` | Before changing a file; identify blast radius |
| `related_tests(path_or_symbol)` | Before adding or changing tests |
| `search_code_semantic(query)` | When the behavior is known but the location is not |
| `summarize_changed_files(base, head)` | Before building on top of branch changes |

Operating rule: Meridian first. Files second. Search last.

## Change Hygiene
- Before editing: summarize intended edits and target files.
- After editing: summarize exactly what changed and any follow-up verification steps.
- If instructions conflict or are ambiguous, stop and ask for clarification.

## Uniqueness Lives in the Sponsor's Info-Sphere

**Very few things are unique across the whole system (CTO, 2026-10-23).** A record's slug, name or title is unique within its sponsor's info-sphere (a member's, or a group's), not platform-wide. Content that a member or a group can own takes a polymorphic sponsor and sponsor-scoped uniqueness; the standard way is `fundamentals.BaseContent` (sponsor, `UniqueConstraint` on sponsor and slug, a sponsor-scoped `slug_exists`, and a placeholder slug replaced once when a real title arrives). A platform-wide unique constraint needs a stated reason (usernames, for example). Folio was the case that surfaced this.

## Shared Work Between Agents

Several agents work at once (CTO, 2026-10-23). So none overwrites another:

- **Send updates through `puddlejump/agent-inbox/`.** When you finish a unit of work, show the CTO your update for Puddlejump and ask "Send to Puddlejump?" On a yes, write and commit `agent-inbox/YYYY-MM-DD-<agent>-<topic>.md` in the format in its README (commits, build-log entries, Help Fidelity lines, proposed Puddlejump updates, new `zz/` files, open questions). The CTO's yes is the approval; nobody carries notes by hand.

- **Never leave Puddlejump edits uncommitted.** If you change a Puddlejump record for your own work (a status row, a Headnote, a new `zz/` file), commit it in the same session, staging only your own lines. Otherwise, propose it in your agent-inbox update. A file another agent has edited but not committed holds their work: don't commit, revert or reformat their lines.
- **Puddlejump writes the shared logs.** Put your build-log entry and your Help Fidelity lines in your agent-inbox update; the Puddlejump session files them in `build-log-inbox/`, `build-log.md` and `HELP_FIDELITY.md` from it. One writer per shared log.
- **New `zz/` files:** name them in your agent-inbox update so Puddlejump commits and tracks them.
- **`packages/api`:** edit only your own client folder (for example `clients/shuttle/`, `clients/folio/`), and say so in your update before touching a shared index or barrel file.
- **Contour is the source for Shape schemas** (`puddlejump/reference/contour/`). A copy in core or `packages/api` is never edited on its own: change Contour first, then the copy.

## Commit Handoff

After completing a commit that has been approved by the CTO, produce a
handoff entry in the format below and include it in your agent-inbox update
(see Shared Work Between Agents): the CTO approves sending, and Puddlejump files
it. Do not write to `build-log.md` or `build-log-inbox/` yourself.

    Repo:         mixtape-release-core
    Commit:       [short hash] — [one-line commit message]
    Date:         [YYYY-MM-DD]
    Work effort:  [ADR or initiative this belongs to]
    What was built:
      [2–4 sentences — what was implemented and why, written for someone
      reading this log months from now. Name the models, endpoints, or
      surfaces involved. Avoid vague summaries like "fixed some bugs."]
