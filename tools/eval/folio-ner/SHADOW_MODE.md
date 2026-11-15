# File-only Selene shadow-mode runner

MA built this runner under the CTO's 2026-11-15 authorization to build and review
it, changing the earlier NER Eval/MA split. Governing plan:
`puddlejump/zz/plan-se2-shadow-mode.md` (F1–F7 accepted, November 14).
This is stage-1 evaluation tooling, not a Folio feature or SE-2 rollout.

Only the CTO runs it over their own notes. Agents must not open the input,
workspace, evidence or review files. The CTO may share the emitted tallies and
individually chosen cases. No database export command is included or executed.
The previously filed aggregate-only count command remains CTO-run.

## What it does

- Freezes exact input bytes as decoded UTF-8 text, raw source hashes, capture
  order, Folio local-only flags and transcript provenance in a new private
  workspace. No normalization or truncation of sources.
- Assigns tuning/holdout (approximately 80/20) deterministically from a supplied
  seed and source hash before inference. Identical texts stay in one split.
  Independently selects approximately a fifth for unaided-first annotation.
- Requires completed unaided annotations before showing any candidates. This is
  a procedural bias check, not a secure blind study; the owner can read files.
- Verifies the complete pinned GLiNER package and Contour bundle; checks the
  current two-label profile, runtime versions and committed, clean runner/adapter
  sources. Offline UUIDs bind wire validation but never represent real ActionRuns.
- Loads one GLiNER adapter lazily for all eligible notes in that invocation.
  Process exit releases the model. An all-character-budget-refused set never
  loads it. No scheduling, service invocation, provider fallback or retries.
- Saves each completed note separately, exact wire response, preflight words and
  tokens, elapsed inference, raw scores, cue spans and typed refusals. Blank,
  over-budget and candidate-budget refusals remain in the denominator.
- Creates a private review template with original source, each candidate, exact
  Shape description/disambiguation/version and a wording hash. Descriptions
  come from Contour, not a new interpretation of Character or Setting.
- Imports each completed human review as a new snapshot, without overwriting
  earlier or repeated judgements. Actor and timezone-bearing time are required.
- Produces text-free tallies: per-split exact and maximum one-to-one typed-overlap
  counts, Wilson intervals for precision/recall/refusal rates, errors, can't-tell,
  candidate ambiguity/uncertainty, overlap pairs, actions/time, score-band outcomes
  and conditional candidate-exact Brier scores. Empty denominators are null.
- Replays an evaluation-only Dictionary using only human-confirmed names in
  earlier notes of the same Folio AND split; gives private per-note revision/hits
  and public per-split model/Dictionary/union counts and recall. No self-note or
  tuning-to-holdout name leakage. Actual Folio capture order is preserved.

Sources, contexts, raw candidates, names, entry IDs, quotes, reviewer identities
and source file names stay private. Public tallies include hashes and code
identity for traceability. Treat even hashes as evaluation metadata; they are
not proof of anonymization. Only `tally` output is intended to be shared.

## Local setup gate

No packages are installed or downloaded by this tool. `freeze`, `review` and
`tally` use Python's standard library. Native `run` additionally needs Selene's
existing pinned GLiNER/torch/transformers versions plus PyYAML, jsonschema and
pydantic; paths must select the reviewed Selene checkout. This checks installed
versions, not a clean combined serving-environment build.

The old scratch `/private/tmp/selene-se-p/env/bin/python` currently lacks GLiNER
metadata (checked November 15). Therefore a native run is **not ready in that
environment**. Restore/approve a compatible environment separately; do not assume
that artifact packaging installed Python packages or fetch replacements silently.

From `tools/eval/folio-ner/`, with the chosen Python:

```sh
python -B shadow.py preflight --selene-root /absolute/path/to/mixtape-release-selene
```

This reads no notes and loads no model. Exit 2 and `ready: false` mean stop.
For `run`, a failed version preflight occurs before opening the frozen inputs.
`run` also refuses uncommitted/untracked runner and adapter source changes.

Turn laptop networking off before native execution. The runner sets offline
flags and refuses Python socket connections and DNS before importing model
libraries; that is not an OS firewall. Library stdout/stderr are suppressed so a
library exception or log cannot print private text. Failures print fixed codes,
not exceptions containing model input. Do not collect a full traceback on real
notes for an agent to inspect.

## Owner-run workflow

Choose one private directory outside every Git tree and check its backup/sync
policy. The runner rejects Git ancestry, including linked-worktree `.git` files,
and symlink ancestors. Workspace permissions are 0700; generated files are 0600.
It creates new files/directories and refuses overwrites. It does not delete files.
Keep private copies until the decider findings are accepted, then delete text
according to the CTO's F5 decision, retaining only approved tallies/hashes.

Prepare UTF-8 JSONL outside Git, one note per line with exactly these fields:

```json
{"note_id":"00000000-0000-0000-0000-000000000001","folio_id":"00000000-0000-0000-0000-000000000002","capture_order":0,"local_only":true,"medium":"typed","transcript_model":null,"transcript_backend":null,"text":"An owner-supplied note."}
```

`note_id` and `folio_id` are canonical UUIDs. Capture order is a nonnegative
integer unique within each Folio. For voice, `medium` is `voice` and both
transcript fields must identify the actual model/backend. Unknown provenance
must be established by the owner, not fabricated by the runner. Exported text
must be the original captured source, including any explicitly retained correction.
The runner makes no automatic database/source-completeness claim.

```sh
python -B shadow.py freeze --input "$PRIVATE_INPUT" --workspace "$NEW_WORKSPACE" --seed pilot-2026-11-15
```

Choose and record the seed before studying the set. `freeze` creates
`frozen.json` and `unaided-template.json`. Copy the latter to a new private file
and fill it: mark `complete: true`, actor/time, and all unaided Character/Setting
mentions as `{start, end, role}` using original Python code-point offsets. No
mention is `[]`, not an incomplete record. Even empty blind samples need no
invented annotations; omit `--unaided-review` when there are none.

After preflight is ready, with networking off:

```sh
python -B shadow.py run --workspace "$WORKSPACE" --model-package "$PACKAGE" --selene-root "$SELENE" --unaided-review "$UNAIDED_REVIEW"
```

The durable package root is:

`~/Library/Application Support/Mixtape/Models/selene/gliner-small-v2.1-4e091416cf7c3481db542c2a3d26156916f3a47f`

Expand `~` when setting a shell variable. Use the root holding `manifest.json`
and `artifacts/`, not its `artifacts/gliner/` subdirectory. Optional `--bundle`
selects a complete verified Core Contour bundle; the default is Core's copy.
The result names a new `run-UUID/` under the workspace. A failed run may leave
partial evidence; it has no final `run.json` and cannot be tallied as complete.
A retry is a separate run, never an automatic retry or overwrite.

Copy `review-template.json` to a new private file; preserve all original fields:

- Every candidate: `span_verdict` is `exact`, `wrong_edges` or `not_mention`;
  `role` is `writing.character`, `writing.setting`, `outside_story`, `neither`
  or `cant_tell`. A non-mention cannot simultaneously be a Character/Setting.
- For wrong edges, `corrected_span` is `{start, end}`. Otherwise it is null.
- `entity_ref` is `new`, `cant_tell` or an earlier same-split Dictionary entry ID.
  New IDs are `note_id:start:end:role` (using corrected offsets if appropriate).
  A prior ID means the writer explicitly says the names are the same entity;
  the tool does not infer that from lexical equality. Alternative entries remain.
- Per note: fill actor, timezone-bearing ISO `reviewed_at`, `complete: true`,
  integer `seconds` and `actions`; mark omissions in `missed` as
  `{start, end, role, entity_ref}`. Review refused notes too, so refusal is counted.
- Can't-tell candidates stay counted and are excluded from precision/score
  denominators. No forced Character/Setting classification or confidence field.

```sh
python -B shadow.py review --workspace "$WORKSPACE" --run "$RUN" --reviews "$FILLED_REVIEW"
python -B shadow.py tally --workspace "$WORKSPACE" --run "$RUN" --reviews "$IMPORTED_REVIEW_SNAPSHOT"
```

The second command requires the immutable `review-UUID.json` produced by the
first, not the editable input sheet. It stores a new private Dictionary replay
(with quotes) and text-free tallies file, and prints only those tallies. Share
that output if desired. Review imports and subsequent tallies validate frozen
set, run, evidence, unaided and wording identities. They cannot rewrite candidates.
Review again by importing another completed sheet; the previous snapshot stays.
Select one snapshot explicitly when tallying, never silently pool reviewers.

## Diagnostic and interpretation limits

The CTO may choose `--diagnostic-threshold VALUE` explicitly, strictly between
0 and 0.5. There is no chosen/default lower cutoff. It creates a separate profile
ID/digest and private raw diagnostic spans with its own status/candidate cap.
It never changes Selene's globals, accepted profile or exact-profile metrics.
Diagnostic candidate counts are reported separately; semantic review metrics
for this auxiliary run are not implemented. Do not tune on the held-out split.

Dictionary reference rule: NFC(casefold(NFC(value))). Prefix/suffix boundary
alignment prevents partial matches inside expansions or normalization units;
quotes/offsets always address the original source. No accent stripping, fuzzy
matching, implicit entity merging or new word-boundary rule. Pin Unicode database
version and runner hash. Sources above 4,000 code points are explicitly not run
through the reference matcher. This is not a production provider; product
promotion requires the consumer's reviewed implementation to become the source.

This first runner does not calculate repeat-review agreement, entity-identity
false merges/splits, or diagnostic-profile semantic metrics. It retains separate
judgements and entity references for a separately reviewed analysis. The blind
summary is a count comparison, not a corrected/unbiased recall estimate.
Per-note Dictionary growth evidence stays private. One writer's seed split is
not an independent population benchmark; the same Folio can occur in both splits,
but names do not cross splits. Wilson intervals assume independent observations
and are descriptive here; within-writer/Folio correlations can narrow them too much.
No result establishes host fit, latency SLA, calibrated confidence or production
acceptance. Nothing here creates a Sighting, Entity, Folio Dictionary, ActionRun
or a human decision in the application.

## Verification and MA review

Synthetic tests exercise the actual Selene wire validator with a fake model;
no native library/model is loaded and no database is used. Run with a Python
that has Selene's validation dependencies and sibling Selene checkout available:

```sh
python -B -m unittest discover -s tools/eval/folio-ner -p test_shadow.py -v
```

The test's `SELENE_TEST_ROOT` and `CORE_TEST_ROOT` variables can override sibling
paths. MA's review concentrated on private/public separation, source identity,
exclusive writes, no false success on refusals, Unicode alignment and split/order
leakage. Those are covered by tests. Native integration remains blocked by the
missing runtime environment and was not tested on real notes. That environment
restoration and one synthetic native smoke trial are the next review gates,
before the CTO's private pilot. No server step belongs to this workflow.
