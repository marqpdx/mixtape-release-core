# Folio recognition evaluation — M1

Code home: core/tools/eval/folio-ner/. Standard library only. Copied from Mobile's
apps/mobile/pre-tests/folio-ner/ at frontend d0ee754e: recognition.py and
its eight original tests are unchanged. Mobile's source tree was left alone.

The CTO moved this M1 session from Cass to the laptop while Cass provisioning
continues (2026-11-03). This host change authorizes no models or downloads.
M1 prepares proposed cases, contracts and an evaluator. M2 needs a separate go.

## Run from this folder

```sh
python3 -B run.py compile --check
python3 -B -m unittest discover -v
python3 -B run.py baseline --split tuning
python3 -B run.py baseline --split contrast
python3 -B run.py baseline --split paraphrase
```

No default pooling of splits. The five holdout cases remain distinct; M1 does
not use them to tune or report baseline performance; they remain reserved for M2.
For a future adapter, choose a split explicitly, export requests with
`run.py requests --split contrast`, run the persistent adapter's JSONL input/output
process and score its saved output with
`run.py evaluate --split contrast --responses /path/to/output.jsonl`.
`run.py adapter` is the deterministic cue-only JSONL process, reading stdin.
There is no automatic model installation or invocation in any command.

`compile` regenerates cases.jsonl from cases.source.json and the accepted
release-local Contour bundle in app/heddle/contour_bundle.json. It computes exact
code-point spans from quote annotations, requiring an occurrence for repeated
quotes, plus immutable source/annotation hashes and full request identity.
Regeneration is an explicit fixture action; inspect changed hashes before
accepting them. --check detects fixture/Contour drift without writing.

## Artifacts and current limits

- cases.source.json: 21 synthetic cases and readable quote annotations, with per-case review status.
- cases.jsonl: reproducible exact spans, digests and pinned request snapshots.
- CASE_REVIEW.md: human-readable texts, gold proposals, ambiguities and non-actions.
- CONTRACT.md: JSONL fields, Heddle mapping and Mobile interface review.
- M1_STATUS.md: observed verification and remaining CTO acceptance gate.
- recognition.py/test_recognition.py: unchanged source scaffold from d0ee754e.
- adapter.py/dataset.py/evaluation.py/run.py: contract, compilation and harness.
- test_m1.py: boundary/identity/scoring/dataset integrity regression tests.

CTO review/amendments A1–A5 are recorded in CASE_REVIEW.md; three added cases
are explicitly marked authored to the CTO specification, not individually reviewed.
The baseline recognizes vocabulary cues only; it emits no name mentions, learned
aliases, Sightings or Entities. Its negation/ordinary-use heuristics have known
limitations; reports expose qualifier errors rather than silently tuning the
baseline to pass the cases. No spaCy/GLiNER/local semantic/Claude model ran.
No Model Vetting result is appropriate until a real model run occurs.

M2 must pin exact model/package revisions and follow Model Vetting Tier 0 before
fitness judgments. Private CTO notes stay outside git and are not part of M1.
A subsequent Cass/laptop shift must carry committed artifacts and the host
correction through the NER Eval inbox. No production dependency or setting changed.

## CTO review conventions (2026-11-03)

Leading articles stay outside mention spans. Possessive 's stays outside the name.
The descriptive baker mention is optional gold (`optional: true`): one exact
correctly typed hit is neutral in required metrics, and optional hits are reported
separately. Its absence is never a false negative; duplicate predictions remain
false positives. Exact metrics remain primary; maximum one-to-one typed overlap
scores are supplemental. No blind normalization of source text is allowed.

The 21 cases include an 812-character spoken self-correction in holdout, a
229-character spoken note without Shape cues, and a possessive/multi-word-name
case. The mixed decomposed/precomposed accents are intentional and tested.
`python3 -B report.py` rebuilds CASE_REVIEW.md, baseline_summary.json and review
provenance from compiled fixtures; it evaluates only tuning/contrast/paraphrase.
The second reader, Puddlejump, accepted CONTRACT.md as M1's draft format.

## M2 laptop comparison (2026-11-04)

CTO advanced M2/M3 for a prospective author who cannot use cloud AI. This is
local evaluation, not approval for privacy-facing production rollout.
`model_adapters.py` adds lazy-loaded spaCy/GLiNER adapters; M1 stays standard-library
only. The isolated environment lock is m2-requirements.lock. Exact model sources
and file hashes are in m2-model-manifest.json; model files stay outside git.
Tier 0 raw outputs are in m2-tier0.json, including the missing-protobuf harness
failure and successful repeat. Encoder models do not use chat templates.

spaCy: 3.8.18 / en_core_web_sm 3.8.0 (MIT). GLiNER: 0.2.30 /
urchade/gliner_small-v2.1, revision 4e091416cf7c3481db542c2a3d26156916f3a47f
(Apache-2.0), with DeBERTa tokenizer/config revision pinned in the manifest.
The runtime config changes only model_name to the local encoder directory; the
original config is retained and hashed. Runtime weights point to the original
pinned weights. Evaluation uses CPU, two torch threads, seed 0, fixed threshold
0.5, labels character/setting/scene and flat_ner=False. No tuning on holdouts.

Generic spaCy PERSON maps provisionally to Character; GPE/LOC/FAC to Setting.
It has no Scene NER mapping. These are evaluation hypotheses, not confirmation
that a mentioned person or location belongs to fiction. GLiNER's returned label
is likewise provisional. Original offsets and quotes are validated without
article trimming, possessive repair, normalization or duplicate suppression.
The unchanged cue baseline is included independently in both adapters.

Run `run_m2.py --backend spacy --split tuning --model-root /private/tmp/ner-m2-models
--output /private/tmp/ner-m2-runs/spacy-tuning` using the isolated Python; choose
one split explicitly. Replace backend/split/output as needed. The runner requires
its source and lock committed and clean, verifies downloaded artifact hashes,
and saves raw predictions, contract responses, exact/overlap scores, errors,
code/model/data/context identities and resource timings outside git.

All measured samples are synthetic. Private notes remain excluded, holdouts are
never used for tuning, and no Claude baseline runs without its own approval.
M3 remains a separate found-mention semantic comparison, including abstention;
a full end-to-end local reading needs more than successful name recognition.
