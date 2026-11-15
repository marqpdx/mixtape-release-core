# SE-2 local recognition integration — local implementation, default disabled

2026-11-14 · MA (Codex). Implements the accepted November 13 Blue/Abe design;
the original packet's proposed/review-requested wording is historical.
SE-0/SE-1 and their accepted reviews were not restarted.

Core/Heddle now supports explicit local model Steps on its existing ordered
lifecycle and ActionRun store. Backend/profile identity participates in the plan
digest. Folio's separate `writing.fiction_note_recognition/0.1.0` factory runs
preparation and deterministic Character/Setting cues, dispatches one actual child
for the entire ordered request, then validates and assembles recognition evidence.
It never creates canonical Sightings, Entities, Dictionary entries or human
decisions, and never writes the old note.mentions projection. Successful actual
steps remain succeeded; coverage is partial/recognition_only, semantics not_run.

The broker carries the child reference/fingerprint, not source text. Core's
`POST /api/folio/recognition-executions/{execution_action_run_id}/claim` requires
the existing deployment-keyed Switchboard credential with the new isolated
`folio:recognition:claim` scope. It rechecks the attested active person, personal
Folio access, live note location/source, parent/child/tenant/mode, current complete
context/Strategy/bundle/profile/request identity, then serializes the claim on
the existing parent/child rows. A second in-flight delivery is unavailable,
never another model call. Authorized terminal children support apply replay.
Failed principal/claim checks never finalize another caller's child.

Switchboard's async capability, REST capability route and registered G/read_only
MCP tool all use the same claim/policy/local-client seam. They reuse Core's child
instead of creating a second execution ActionRun. Configuration binding is
validated and a disabled tool in any system/deployment/tenant layer wins; the
tool itself is always local-only. Cloud requests fail `policy_forbids_cloud`.
After a successful claim, policy/host failures finalize that owned child and
dispatch only the fixed recorded Folio callback. Timeout/lost replies never
trigger automatic inference retry. Terminal replay only retries apply.
Core rechecks current authority/context/plan and validates the exact response at
apply; duplicate callbacks have no second effect. Model provenance is bound by
Core to the actual child; model_calls=1 counts that request, not tensor passes.

MCP registration grants no existing token a new execution right. The new handler
requires the explicit `ariadne.recognize_mentions` token scope; legacy broad read
tokens refuse. No Surface configuration, token scope or allowlist was modified.
REST retains Core authorization and the claim's personal-resource authority.

## Folio restriction

Additive migration `0007_folio_local_only` adds default-false `Folio.local_only`.
Serialization exposes it read-only. The authenticated owner command
`POST /api/folio/folios/{folio_id}/local-policy` accepts a strict JSON Boolean,
expected context revision and request UUID; it remembers replay/conflict receipts,
updates context identity and never dispatches inference. Current authoritative
Folio flags guard Heddle cloud dispatch and the Core cloud worker. They cannot be
overridden by a caller's false flag or cloud consent. Existing composed-reading
chains explicitly refuse implicit recognition Strategy replacement.

This is **not an end-to-end transcription local-only claim**. SE-3 retains all
ten transcription callers, audio grants, selector compatibility and its own
high-risk approval. The phone control and public recognition/Dictionary
read/command schemas remain their owners' separate work.

## Dependencies and rollout gates

- Core `FOLIO_RECOGNITION_ENABLED` and Switchboard
  `selene_recognition_enabled` default false. Selene recognition remains false.
- Core has no authoritative Dictionary provider. The internal registration seam
  requires its owner's reviewed Folio-scoped revision/entries snapshot and refuses
  `dictionary_unavailable` when absent. Synthetic tests supply a fixture provider;
  production has none. Existing note.mentions is never substituted. Public
  schema/provider integration is still a Blue/consumer dependency, not delivered
  by this slice. No new public begin/read/execute schema is invented here.
- New Switchboard host clients require their own `selene_service_jwt_kid` and
  secret; Selene verifies against `service_jwt_secrets`, keyed by deployment.
  An unknown/missing key in map mode never falls back to the old single-host
  skeleton setting. Kid-bearing clients refuse legacy single-host mode. No
  secret was read, generated or provisioned, and no real auth/network trial ran.
- Service/profile schemas are byte-for-byte accepted packet copies. The full
  model/encoder/tokenizer/dependency packaging limits from the November 14 resume
  remain: no clean combined ASGI/model serving rebuild or live host-fit claim.
- BA2/CTO host fit, OS egress denial, single-process placement, credentials and
  production enablement remain separate gates. No model/package download,
  server change, push or deployment occurred. No cloud API was called.

Rollback: disable recognition in Core/Switchboard/Selene. Preserve the additive
policy field and cloud guards, captured sources and actual child/history rows;
do not roll back to a cloud path that ignores an existing local-only restriction.
The CTO runs server/production steps personally; this document runs none.

Validation is reported with the implementation commits in MA's agent-inbox
update. Tests use synthetic sources, mocked host/broker calls and an isolated
local PostgreSQL test database; two-connection claims and callbacks exercise real
row locks. Model-quality evidence remains the already-filed separate trial.
