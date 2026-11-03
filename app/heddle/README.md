# Heddle: ordered readings and the Contour bundle

HD-5 / ADR-0061, 2026-11-03. Shared mechanics only: no Folio models,
capability registration or deployment are included in this unit.

## Opt-in contract

Legacy Readings without `steps` retain their existing lifecycle, public snapshots,
task names and single model call. Shuttle remains on that path.

An ordered Reading supplies versioned `Step` definitions, a `context_provider`,
Strategy identity/version and surface `validate_findings` callback. Each Step names
input/output contract versions, prerequisites and required/optional status.
Deterministic steps supply `run`; model steps supply `build_prompt` and a JSON
response schema. Optional validators and skip predicates are deterministic hooks.
The provider returns an authoritative JSON context snapshot with an integer
`revision`; source preparation adapters must bound and authorize that context.

`begin` records source/context identity. `execute` additionally requires the exact
`expected_context_revision` and `context_digest` shown in the snapshot. It records
consent for the named steps before dispatch. Steps and attempts live in the
existing parent ActionRun request payload, not new tables. Only real model steps
create children, using the shared Switchboard dispatch and Claude worker. Model
outputs and deterministic outputs carry actual step states; partial readings are
never labelled successful. Explicit retries retain previous attempts/Sightings.

A surface changes its own context deliberately, then calls
`heddle.ordered.refresh_context` with the old expected context revision. Changed
contents require an increased revision. This supersedes prior results without
cloud dispatch. Authoritative context is checked again before dispatch, before
Claude and before result application. Source, context, Strategy, prompt, bundle,
step definitions and payload fingerprint bind approvals and executions.

`Reading.reference_fields` declares reference field names and allowed target
Shape ids for shared existence/type checks; surface validators add meaning rules.
Common schema, duplicate-id and exact Unicode code-point span checks run before
checked success. The default prompt ceiling is 150000 characters; it errors
rather than truncating. Folio's source/context/vocabulary budgets and semantic
hooks belong to the next reviewed surface slice.

No automatic local/cloud fallback exists. New ordered readings return
`backend_unavailable` when configured local until an approved local adapter exists.
The generic path is tested with synthetic Readings, not a registered Folio tool.
Future Folio Switchboard registration must accept the bound context/step payload
and route through SW-9 to this shared worker; Shuttle's narrow payload is unchanged.

## Contour source and release bundle

`contour_bundle.json` is generated from accepted Contour, never consumer schemas.
It carries the Writing Strategy and all selected Writing/Shuttle Shape schemas,
vocabulary and companion guidance, plus selected manifest metadata, source paths,
versions, hashes and source commit. Shuttle schemas are included for strict
`keep_sighting`; its legacy interpretation contract remains unchanged.

From core/app using the project virtualenv:

```sh
../env/bin/python -m heddle.generate_bundle --contour-root /path/to/puddlejump/reference/contour
../env/bin/python -m heddle.generate_bundle --contour-root /path/to/puddlejump/reference/contour --check
```

Generation requires committed canonical Contour edits. `--check` rebuilds selected
dependencies against the checkout, preserving the original provenance commit so
unrelated commits do not cause churn; it fails on content drift. Production reads
only the shipped bundle. `shape_schema(shape_id, version)` returns a defensive
copy of the exact schema; unknown versions fail, never upgrade. Retained
`<shelf>/versions/*.schema.json` files are included; conflicting versions fail.
No provisional Shape store or field-label proposal wiring is built.

`keep_sighting` now validates the stamped schema before creating ProvisionalData.
Its old weak shape-field check retires. A schema failure raises
`InterpretationError("invalid_sighting", 422)` with `details.path` and
`details.message`, naming offending fields. Ownership and source meaning remain
caller/upstream responsibilities. No schema versions already in use may be
removed when regenerating a release; Contour owns retaining those files.

## Verification

Target `heddle.tests` and `shuttle.tests` with Django test settings and an isolated
PostgreSQL test database. The implementation run used
`crossroads_test_heddle_hd5_20261102`, with no production data or model calls.
Tests cover actual ordered/model accounting, consent, source/context drift,
tampered prompts, runtime changes, retry/history, partial failure, skipped and
unattempted steps, Unicode spans, typed references, strict keeping, generation
reproducibility and retained schema versions. Check canonical bundle drift with
the command above before packaging changes. No migration is required here.
