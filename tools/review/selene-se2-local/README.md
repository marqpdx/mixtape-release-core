# Selene SE-2 local recognition contract — review packet

2026-11-12 · MA (Codex) · **Proposed; no runtime consumer, endpoint, registration,
model installation, migration or live routing is implemented by this packet.**

Authority to prepare: CTO, 2026-11-12: “let's proceed, and i'll handle all pushes.
carry on”; approved Selene planning handoff
`puddlejump/zz/_handoffs/handoff-2026-11-08-ma-selene-planning.md`.
This is the concrete contract review required before the new production
integration, not another request for the already-approved SE-2 phase.

## Review requested

Approve the wire/profile and local execution design below through the CTO to
Blue/Mobile/NER Eval. The phase plan, `puddlejump/zz/build-plan-selene.md`, names
“Production contract alignment goes through the CTO to Mobile/NER Eval” and
SE-2's sign-off includes “contracts, migration, flag surface, client/routing diff
and gate 6b host evidence before enabling traffic.” Canonical
`reference/contour/writing/strategies/fiction-note-recognition.md` requires Blue's
shared API review before consumer/phone implementation. Contour's schema review
and activation are already complete; do not repeat them.

Concrete choices for review:

1. `ariadne.recognize_mentions` is the G/read_only inference capability and MCP
   tool. The host endpoint is `POST /service/recognize`. No `selene.*` tool,
   Inkwell detour, cloud fallback, record mutation or Surface grant is implied.
2. The two-label profile below is a **new proposed production profile**, not
   the three-label evaluation result relabelled. One child ActionRun represents
   one whole multi-source request; original/correction source boundaries survive.
3. Keep the existing one-note/person `FolioInterpretation` chain. Reuse only if
   its pinned Strategy is recognition. An existing composed-reading chain gives
   `strategy_conflict` (409); no silent replacement, second table or uniqueness
   migration. A future explicit Strategy-switch/history command needs review.
4. Refuse input outside the complete model budget with `source_too_long` (413).
   No chunks, discarded corrections, source concatenation or silent truncation.
   Existing 40,000-character capture remains intact and available. This narrows
   the recognition execution budget, not the capture/transcription API.
5. A narrow Core claim operation rechecks the recorded local child, principal,
   Folio/note authorization and exact source/context/plan before Switchboard
   sends any text to Selene. Reuse deployment-specific Switchboard→Core auth;
   do not reuse the general internal key or provision credentials in this unit.
   This proposed endpoint extends the current AC-5a endpoint allowlist and needs
   paired verifier/client tests and explicit auth-contract review before use.

## Files and evidence

- `request.schema.json`, `response.schema.json`: proposed Draft-7 wire schemas.
- `profile.json`: exact proposed task profile; its canonical JSON SHA-256 is
  required by both envelopes and every model producer.
- `request.example.json`, `response.example.json`: entirely synthetic golden
  examples with non-BMP/decomposed Unicode and an append-only correction.
  Fake bundle/step/input digests illustrate syntax; they are **not valid proofs
  of a real bundle, plan, source owner or execution**.
- `verify_contract.py`: offline schema/meaning rehearsal; **not production
  validation code and not imported by services**. It rejects unknown wire,
  binding, candidate and producer fields; strict identity/span/score checks
  supplement JSON Schema. The opaque context is deliberately surface-owned:
  its full canonical hash is checked here, its exact authorized vocabulary and
  current revision must be checked against Core's context provider at execution.

Validation, using the existing Core environment (no install or database):

```sh
env PYTHONDONTWRITEBYTECODE=1 env/bin/python tools/review/selene-se2-local/verify_contract.py
```

**33 checks passed on 2026-11-12.** This includes each echoed binding field,
source/context/bundle mismatch, aggregate input budget, duplicate source/candidate,
exact non-BMP/decomposed spans, normalized-quote refusal, invalid UUID, booleans or
floating revisions, invalid/non-finite scores, unsupported Scene/labels,
canonical Sighting fields and producer/profile mismatches. Empty candidates are
valid only as wire data; service and ActionRun checks must establish actual
successful execution rather than fabricating an empty result on failure.

Not tested: GLiNER execution/quality, token preflight against a real loaded model,
service/queue/authorization integration, tenant/source database checks, migration,
static typing, host fit, firewall or live traffic. No inference, private material,
package/model download, network call, credential access or push was performed.

## Wire and meaning

The wire protocol is proposed as `selene.recognition/0.1.0`. The complete strict
schemas are review artifacts beside this file; do not copy them into production
consumers until accepted. They define a task envelope, not a new Contour Shape.
Contour remains the source for canonical Sighting and Dictionary schemas.

The request carries protocol/profile identity, one binding object, immutable
sources, the complete surface context snapshot, and `local_only: true`. The
binding contains the parent/child/attempt, source revision/digest, context
revision/digest, contract/prompt/Strategy versions, ordered Steps/bundle/reference
field digests, and actual model-step id/version/input digest. The source digest
hashes the **whole ordered sources list**, not just the first note or raw UTF-8.
The request fingerprint hashes the entire request using Heddle's canonical JSON
(UTF-8, ensure_ascii=False, sorted keys, compact separators, allow_nan=False).

The complete selected Contour bundle is resolved/validated locally in Core and
pinned in the prepared Step and context identity. No schema retrieval occurs in
Selene. Cue recognition is deterministic Core work, separate from model mentions.
The model receives original source texts and the two pinned labels; the context,
Folio title, cues and Dictionary are identity metadata, not an extra model prompt
or an implicit source of names. The full context remains immutable and bounded.

The response echoes the binding/profile, includes the full request fingerprint
and returns only raw mention candidates. Each has an attempt-scoped id, exact
source locator, Character/Setting hypothesis, finite raw score, explicit provisional
qualifiers and pinned model/profile producer identity. No canonical confidence,
Sighting, Entity, assignment or automatic Dictionary learning is permitted.
`ambiguous: true` denotes unresolved qualification; `negated: false` makes no
semantic negation claim. Deterministic cue qualifiers remain separately recorded.

Candidate id is `m-` plus the first 32 hex characters of canonical SHA-256 over
`{execution_action_run_id, type, source_locator}`. Same-span different-type
alternatives are allowed; duplicate same-type occurrences fail the response.
The server supplies producer metadata from its verified loader/profile, never
copies model-selected provenance. Core independently checks it against the actual
child, bundle and expected profile. Echoed ids and hashes alone grant no authority.

Spans address original Python Unicode code points with exclusive end and exact
quote. Never normalize/casefold source text, use UTF-16/byte offsets, repair a
bad quote, clamp a score, round evidence into confidence or drop unsupported
predictions. Bounds/type mismatches fail explicitly. JSON Schema annotations
alone do not enforce UUIDs, equality, finite numbers or actual source ownership.

## Proposed model profile and complete-input refusal

`profile.json` pins GLiNER small-v2.1 revision
`4e091416cf7c3481db542c2a3d26156916f3a47f`, GLiNER 0.2.30, torch 2.6.0 and
transformers 4.57.3, two CPU threads, seed 0, CPU/fp32 with no new quantization,
labels `[character, setting]`, threshold 0.5, flat_ner=False, multi_label=False.
The versions are those observed in SE-P's existing scratch environment; this is
not a clean-install lock, a new vetting result or a production packaging approval.
Pin the complete approved dependency closure before serving the profile.

Proposed limits: 1–12 sources, at most 4,000 original code points **in total**,
384 GLiNER word tokens per source, 512 encoder tokens per source **including
label prompt/special tokens**, and 256 candidates in total. Context stays within
Core's 40,000-character budget; dependency material stays within the existing
80,000-character whole-bundle budget. Request and response canonical UTF-8 JSON are each capped at 200,000 bytes;
the full context canonical JSON is capped at 40,000 code points. Enforce both
serialized and parsed budgets before registration; this packet does not claim
an ASGI body-size limit exists.

The installed GLiNER processor truncates words and its tokenizer uses
truncation=True. Checking character count alone is insufficient. Preflight all
sources on the shared model thread, using the pinned processor's exact word
splitter and prepared labels plus tokenizer with truncation=False; compare both
word and encoder budgets before the single batched invocation. Refuse the whole
request if any source exceeds either limit or has no tokenizable input. Never
use truncation to implement the limit. One service invocation may contain multiple
native forward passes; model_calls=1 counts an actual execution child/request,
not a fabricated claim about tensor-level forward count. Verify that interpretation
with Blue/NER Eval before implementing batching.

The adapter must reject an output count different from the submitted source count,
unknown labels, non-finite/out-of-range scores, mismatched text/offsets, duplicate
occurrences or output overflow. Retain raw scores; never equate this profile's
threshold with a semantic acceptance threshold. A real run of this exact profile
still needs synthetic verification and a separately reported task-quality trial.

## Proposed local lifecycle and both Switchboard entry points

1. **Begin/inspect:** reuse `folio.interpretation.lifecycle`, authorized
   `member_folios`/`owned_folio`, ready immutable captured source and current
   Fiction orientation. No automatic recognition during capture. Return
   `strategy_conflict` for an incompatible existing chain. Use recognition-specific
   context/dependencies rather than current composed-reading 0.1.0 cue metadata.
   Dictionary persistence/assignment stays Blue/Mobile's separate reviewed unit;
   never invent an empty Dictionary if data exists but its provider is unavailable.
2. **Execute:** Core verifies the exact displayed source/context/plan, explicit
   local command and idempotency key under the existing locks. Extend Heddle's
   Step with an explicit local backend/request builder, retaining current cloud
   behavior for all legacy readings. Include backend and profile/request contract
   identity in plan hashing. Local work needs no cloud consent permission or
   connected Claude runtime. Disabling the service produces unavailable, not cloud.
3. **One actual child:** existing ActionRun store, `execution_mode=local`,
   `cloud_approved=False`, recorded binding/fingerprint/initiator/tenant/resource;
   no source-bearing grants or new pipeline/table. Heddle's deterministic prepare
   and cue Steps run first; only mention_recognition creates a child. Pending
   deterministic records never become fabricated model attempts.
4. **Claim:** proposed
   `POST /api/folio/recognition-executions/{execution_action_run_id}/claim`
   accepts only the attested person/tenant and expected request fingerprint.
   Core loads its recorded payload, verifies parent/child/owner/tenant/source,
   current Folio/note access and location, plan/profile/context/revision, local
   mode and enabled capability, then atomically claims the pending child. It
   returns the authoritative recorded service request; Switchboard never forwards
   broker or REST text merely because it has a matching-looking digest. An
   inactive person, inaccessible/moved/deleted note, wrong tenant/group, stale
   request or already-claimed child refuses before inference. No broad signer,
   general ActionRun reader or new shared credential is proposed.
5. **Async:** specialize `capability_async` before generic mark_running so the
   claim is the sole pending→running transition. Repeated deliveries cannot
   call the model twice. Never finalize someone else's child after a failed
   principal/claim check. Use the recorded Folio callback, not caller-controlled
   task routing. Successful/failed terminal children support apply replay; an
   ambiguous in-flight timeout is unavailable/reconciliation, never blind retry.
6. **Sync/MCP:** accept an execution-child reference already prepared through
   Core, not arbitrary text or a caller-chosen Folio flag. Resolve the REST/MCP
   principal, require the same personal Folio scope (Group tokens refused until
   Group Folio authorization exists), then use the **same claim/policy/client**.
   Do not create a second execution ActionRun around that actual child. Register
   `ariadne.recognize_mentions` as G/read_only; apply normal registry/surface
   access rules without granting a tool to every Surface merely by registration.
7. **Policy:** before any host call, every system/deployment/tenant/tool disabled
   restriction wins. Effective local-only is OR across tool/config/Folio. The
   recognition capability always selects Selene; any cloud request fails typed
   `policy_forbids_cloud`, even with approval or direct entry-point bypass.
   Extend Core's actual cloud dispatch/worker guard to consult the authorized
   current Folio flag; client-supplied false cannot reopen it. Gate denials must
   reach the recorded failed child and existing denied/error presentation,
   without using “Unplaced” or a successful empty result.
8. **Completion/apply:** keep existing terminal ActionRun finalization and
   `heddle.tasks.apply_interpretation`; do not create another result store. Validate
   the wire response against the recorded request and actual producer, then
   recheck current source/context/plan and authorization under the parent lock.
   Superseded execution remains on its child/history, never overwrites current
   findings. Duplicate callbacks cause no second effect. Model failure halts the
   attempt and leaves dependent checked_recognition unattempted. Core—not model
   echoes—binds the actual execution provenance.
9. **Coverage:** successful actual Steps are all succeeded. The public response
   remains `status=partial`, `scope=recognition_only`,
   `semantic_interpretation=not_run`; retain a separate Strategy execution success
   indicator. No fake semantic Step, semantic error or invented orientation.
   Dictionary matching occurs separately after Heddle, only from confirmed entries
   in this Folio; no model candidate is automatically converted to a Sighting.

## Folio.local_only and rollout boundaries

The approved SE-2 migration is additive `Folio.local_only = BooleanField(default=False)`.
False preserves existing policy while true is a hard restriction, never cloud
permission. Expose it in Folio serialization and an owner-authorized command with
strict Boolean input, expected context revision and operation id/replay receipt.
Advance context identity on change without silently re-reading, include the
current restriction in dispatch and apply checks, and deny cross-member changes.
The wire request's true is the effective recognition restriction, not authority
to change this field. Mobile owns the writer-facing control/denial UI.

Do not mix Dictionary tables, human-assignment/backfill changes, three-Shape
semantic work or Whisper migration into this contract implementation. SE-0's
hard cloud refusals remain. SE-3 still owns all-ten-caller transcription migration,
D8/audio grants, Whisper selector compatibility and its separate high-risk gate.
Until its guards are complete, do not claim Folio.local_only is end-to-end live.

Keep Core and Switchboard capability enablement false by default. Review the
migration/flag/client/verifier diff and tests before any enablement. No deploy,
production config, real secret, source grant or Surface allowlist edit is covered
by this packet. Gate 6b host fit, verified OS internet denial, dedicated service
auth and deployment-level single-process limits remain prerequisites to live use.
BA2/CTO own host acceptance; the CTO handles all pushes.

## Loader boundary for the eventual implementation

Verify a **single complete immutable manifest tree** that includes GLiNER weights,
config, encoder configuration, tokenizer and every artifact they can load before
importing/constructing the model. Reject config references escaping that verified
tree, symlinks, remote identifiers, remote-code hooks and unavailable/unpinned
runtimes. Use only explicit local paths/local_files_only, no cache discovery,
auto-download, dependency install or unreviewed model variant. Preserve the
existing single shared execution thread, bounded admission, queue deadline,
cancellation occupancy and lifetime process lock.

SE-P's current scratch GLiNER config contains an absolute encoder path outside
its runtime subdirectory. Hashing only that runtime directory is insufficient.
Production packaging must either verify the containing encoder tree too or
prepare a reviewed relocatable config/package. Do not silently rewrite hashed
config to make loading pass. No accepted production artifact manifest or full
profile-quality evidence is supplied by this review packet.

## Required paired implementation verification after review

- Contract parity at producer, client and Core validator, including every golden
  and malformed example; strict serialization/size limits and sanitized errors.
- Source/Folio/person/tenant/Group authorization and changed-context/plan/profile
  checks at execute, claim and apply; concurrent claim/replay/lost-response and
  callback races against an isolated test database.
- Both REST capability and MCP/async paths exercise the common policy seam;
  any-layer restriction wins and direct bypass cannot cause a cloud call.
- Existing Heddle cloud and 0.1.0 composed-reading regressions remain unchanged;
  real local child lifecycle and truthful partial coverage are demonstrated.
- Migration/owner flag commands, revision/replay conflicts, stale captures and
  typed denials; no auto-created Sighting, Entity, Dictionary entry or decision.
- Pinned loader/token preflight and synthetic real-profile inference, no network
  retrieval even on missing encoder/tokenizer, busy/cancel/error propagation,
  affected type checks and canonical bundle drift. Host evidence is separate.

## Governance closeout

This review packet changes only Core's `tools/review/selene-se2-local/`.
Other agents' service-unit changes or staged lines are not part of it. No
Puddlejump shared log, handoff Resolution, Help Fidelity or Sheaf is edited by MA.
After the CTO approves sending, commit the agent-inbox report carrying the actual
commit, these validation limits and the production-contract review request.
SE-2 remains in progress, recognition execution/registration unbuilt.
