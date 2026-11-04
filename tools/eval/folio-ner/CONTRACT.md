# M1 recognition JSONL contract — 0.1.0-draft

Offline evaluation format, reviewed against core Heddle b7c4d977. This does not
register a capability, introduce a production endpoint or amend a Contour Shape.
Request and response validators live in adapter.py; only Python's standard
library is required. JSONL means one complete JSON object per line.

## Request

`contract_version`, `source`, `source_digest`, `context`, `context_digest`,
`step_id`, `step_version`. No additional outer fields.

- source: exact `source_ref`, integer `source_revision`, original `text`.
- source_digest: SHA-256 of Heddle's canonical JSON serialization of `[source]`,
  not the plain text hash. Dataset `source_sha256` separately hashes raw UTF-8 text.
- context: integer `revision`, explicit Fiction type/title, accepted Strategy
  id/version, Contour identity and the full selected Writing cue vocabulary.
- contour: library id/version, bundle digest and source commit. Each vocabulary
  row pins shape_id/version, scalar cue terms and canonical path/content hash.
- context_digest: Heddle-compatible canonical JSON hash of that full snapshot.
- step_id/version: the caller's step identity. M1 uses `recognition_eval`/0.1.0
  as an offline evaluation label, not a registered Strategy step.

The request carries one source per recognition unit. A later Heddle adapter may
invoke it for each immutable source; it must preserve the outer reading's full
source/context identity and record that mapping. This unit must not claim its
single-source digest identifies an entire multi-source reading.

Shape cues, confirmed Entity aliases, project markers and field labels are four
separate context collections. Current fixtures have no confirmed aliases,
markers or labels. They must never be silently interchanged. The narrow cue
reader extracts only the current scalar-list representation from the verified
Contour bundle; unsupported YAML structures fail explicitly. No new YAML parser
or canonical synonym list is invented in this tool.

## Response

The response echoes `contract_version`, `source_ref`, `source_revision`,
`source_digest`, `context_revision`, `context_digest`, `bundle_digest`, `step_id`,
`step_version`, and supplies `candidates`. No additional outer fields.

Each candidate contains exactly:

- candidate_id: unique within this response; not a Sighting or Entity id.
- candidate_kind: cue or mention. Score these collections separately.
- type: writing.character, writing.setting or writing.scene. A label hypothesis,
  not confirmation. Broader annotation/semantic judgments are scored separately.
- source_locator: one object with Heddle's exact `source_ref`, `source_revision`,
  inclusive `start`, exclusive `end`, and verbatim `quote`. Offsets are Python
  Unicode code points, without normalization; never UTF-16 offsets or bytes.
- score: null for rules; optional finite uncalibrated model value in [0,1]. Not
  Heddle's high/medium/low confidence or an acceptance threshold.
- negated/ambiguous: boolean evidence qualifiers, never acceptance decisions.
- uncertain: an array of reason strings for this recognition contract. It is
  not the structured `uncertain` field in a Contour Sighting.
- producer: kind (rule/model/prompt), id, version and model_revision. Model/prompt
  output requires a pinned model revision; rules have no model revision/score.

A recognition candidate never carries sighting_id, status, confidence or payload.
A later semantic step may use it as evidence while producing canonical flat
Sightings with the six-field envelope and their own Shape fields. For a canonical
Sighting, source_locator is an array; the singular candidate span becomes an
array element only when that semantic step deliberately constructs the Sighting.
No conversion is performed by this evaluator.

## Mapping to ordered Heddle steps

A deterministic Step.run can call the offline adapter and retain the response as
its output. Output digests and real step states belong to Heddle's parent record;
this response neither fabricates state nor claims an ActionRun. A measured model
adapter later gets the normal execution accounting and routing through Heddle /
Switchboard. No new runner/pipeline is implied by this JSONL process seam.

State source_revision maps to the immutable source's revision; context_revision
maps to snapshot.revision. The full parent attempt/request fingerprint remains
outside this task response. Changing text, revision, vocabulary, context or step
identity invalidates an old response. Missing/duplicate responses fail evaluation,
not convert to a fabricated successful empty recognition.

## Evaluation boundaries

Evaluate exact label + span separately for cues and mentions. Lexical cue recall
can be perfect while semantic qualification is wrong, so qualifiers and ordinary
usage false positives are reported alongside span scores. Duplicate predictions
count as false positives. Per-type precision/recall/F1 and boundary/type error
lists are produced; empty denominators are null. Wrong source/revision never match.

Scene narrative judgments are separate annotations, not gold name-mention spans.
Nothing here measures Entity identity, coreference, relationship inference,
orientation, narrative composition or eventual placement quality. M2 must retain
these boundaries when comparing rule/spaCy/GLiNER/Claude outputs.

## Mobile interface review

Reviewed in the joint laptop session, 2026-11-03, in the Mobile role: the format
matches Heddle hashing, revisions, span fields and pinned Contour identities;
recognition evidence stays outside the Sighting envelope and state/accounting
stay outside candidates. Suitable as the M1 draft comparison boundary. This is
an interface sign-off, not a production registration or model-quality decision.
This author check was followed by Puddlejump's independent second-reader review:
accepted as the M1 draft format, 0.1.0-draft, under the CTO-approved November 3
NER M1 review handoff. Dataset amendments A1–A5 are applied; stop before M2.

## Reviewed gold and scoring amendments

Mention annotations may carry `optional: true`. A correctly typed exact match to
optional gold is neutral in TP/FP/FN and is reported in `optional.hits`; absence
has no penalty. Required gold matches take priority; extra duplicate predictions
still count as false positives. Optionality is an annotation property, not model
output or a Sighting acceptance decision. Unspecified optional means false.

Leading articles and possessive 's are outside mention spans. The evaluator also
reports maximum one-to-one same-type overlap as a supplement to exact metrics.
All overlap comparisons preserve source identity/revision and keep cue and mention
pools distinct. Source normalization and alias learning remain prohibited.
