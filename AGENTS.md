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

## Commit Handoff

After completing a commit that has been approved by the CTO, produce a
handoff note in the format below and present it clearly so the CTO can relay
it to the Puddlejump session for logging. Do not write to Puddlejump yourself
— the CTO is the gate.

    Repo:         mixtape-release-core
    Commit:       [short hash] — [one-line commit message]
    Date:         [YYYY-MM-DD]
    Work effort:  [ADR or initiative this belongs to]
    What was built:
      [2–4 sentences — what was implemented and why, written for someone
      reading this log months from now. Name the models, endpoints, or
      surfaces involved. Avoid vague summaries like "fixed some bugs."]
