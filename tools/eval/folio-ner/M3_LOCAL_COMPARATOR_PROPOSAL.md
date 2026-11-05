# M3 small local comparator — approval proposal

2026-11-05 · NER Eval · **not downloaded, installed or run**

Answers step 3 of the approved November 5 Mobile/NER Eval handoff. The CTO's
specific go-ahead for this comparator precedes download/install/Tier 0. Case
review is separate; no fresh-case inference before the case set is approved.

## Exact candidate

- Publisher/repository: **Qwen/Qwen2.5-0.5B-Instruct-GGUF**.
- Revision: **9217f5db79a29953eb74d5343926648285ec7e67**.
- File: **qwen2.5-0.5b-instruct-q4_k_m.gguf**, Q4_K_M.
- Size: **491,400,032 bytes** (about 491 MB decimal / 469 MiB).
- Expected SHA-256: **74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db**.
- Licence: **Apache-2.0**, per publisher metadata/card; retain the pinned LICENSE
  and README alongside the artifact when downloading.
- Runtime proposal: **llama-cpp-python 0.3.15**, matching the current Inkwell
  requirements.txt pin. Use an isolated laptop environment; change no Inkwell or
  core production dependency. Record resolved dependencies, vendored llama.cpp,
  compiler/build flags and actual chat template before a measured run.

Primary sources, checked 2026-11-05:
[publisher card](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF),
[pinned file](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/blob/9217f5db79a29953eb74d5343926648285ec7e67/qwen2.5-0.5b-instruct-q4_k_m.gguf),
[metadata](https://huggingface.co/api/models/Qwen/Qwen2.5-0.5B-Instruct-GGUF?blobs=true).
The API supplied exact size and LFS SHA; only metadata was fetched. Do not use
unpinned main or an illustrative download-size estimate as the artifact identity.

Why this candidate: a deliberately small generative baseline for one four-label
judgement, via Inkwell's runtime family. It is not selected as a full Fiction
reader, prose generator or production replacement. Smallness is a hypothesis
about fit, not evidence of role discrimination. A failure after correct wiring is
a task result; a load/template/file failure is a harness issue, not disqualification.
The older vetting incident involved another Qwen file/configuration; do not infer
the same failure here without testing this artifact.

## Decomposed unit: one selected span and bounded context

Proposed unit name: `m3_span_role` 0.1.0-draft. This is evaluation terminology,
not a new registered capability or canonical cross-pipeline registry entry.

1. **Prepare target/context (deterministic):** source reference/revision/hash,
   selected original span, containing sentence(s), explicit Fiction context and
   pinned relevant Contour vocabulary. Preserve original text; never pass gold
   expected_label, rationale or evidence_proposals into model input.
2. **Judge role (one local generation):** is this selected name/passage a Character,
   Setting, Scene or none in the telling? If evidence is insufficient, abstain
   distinctly. Do not find every name, rewrite narrative, resolve identities,
   propose aliases, confirm orientation or create records in this call.
3. **Check evidence (deterministic):** reject malformed labels/JSON; resolve exact
   quoted evidence plus occurrence against the supplied original context. The
   model should judge meaning, not do code-point arithmetic. Missing/ambiguous
   or invented quotations fail rather than being repaired.
4. **Score/report (deterministic):** label confusion, positive/negative performance,
   abstention, evidence validity, failures and resources. Gold is used only here.

Each unit materializes its prompt, response schema, source/context/vocabulary
identity, runtime/settings and output. No whole-Folio prompt and no one generated
answer impersonating multiple actual executions. The model call gets one actual
execution record; deterministic checking does not get a fake model child.

Proposed judgement response for review:

```json
{
  "decision": "classified",
  "label": "writing.character",
  "evidence": [{"quote": "Within the fiction, Suri is the editor", "occurrence": 1}],
  "uncertain": []
}
```

Labels: writing.character, writing.setting, writing.scene or none. With
`decision=abstained`, label is null and uncertainty explains why; do not treat
absence of a GLiNER prediction as an explicit semantic none judgement. Unambiguous
gold units keep abstentions in the denominator and report them separately, rather
than scoring uncertainty as correct rejection. At most three exact evidence
quotes and three short uncertainties. This is a proposal, not a schema installed
in Heddle or a consumer contract change.

The role model receives the complete **selected classification vocabulary**,
not an arbitrary first-N truncation of the full shelf. Propose a deterministic,
versioned projection of id/version, description, representation, cues and full
disambiguation from all three pinned Writing definitions. Record each source
file hash and the derived artifact hash; retain the complete source bundle for
audit. No invented/truncated definitions. Review this explicit unit projection
before execution; M3 does not need the attribute-generation schemas/templates
used by a composed reading. If existing whole-bundle rules require a different
payload, resolve that rather than silently dropping dependencies to fit.

## Execution profile and budget

Propose CPU baseline, two threads, n_gpu_layers=0, temperature 0, seed 0,
n_ctx=8192 and max output 256 tokens. These are logged experimental parameters,
not semantic first-N caps or a claim of production capacity. Verify actual token
counts using the actual template/tokenizer, reserving output and control-token
space. Fail over-budget input explicitly; do not drop evidence, change backend
or increase a model setting silently. Per-unit safety timeout is recorded as a
failed/unknown result, never automatic cloud escalation or a retry permission.

No batching decision changes the unit boundary. The broader Field Note's consent
bookkeeping and monthly registry/cadence are not adopted by this experiment.
The local-only author's material remains local-only; no private note is in this
proposal. A future Claude comparison needs its own explicit approval and runtime.

## Tier 0 before corpus scoring

1. Verify exact download hash, load, inspect GGUF metadata and get a coherent
   trivial raw completion. Log failures without making a task verdict.
2. Verify the actual instruction/chat template, then a trivial instruction answer.
   Use the artifact's embedded template or a demonstrably matching explicit
   format; do not guess ChatML just because another Qwen model used it.
3. Run a short approved review example for this exact role/evidence task. Confirm
   structural sanity before scoring the reserved cases. Preserve raw output.
4. Pin all code/artifacts/profile and freeze reviewed cases before measured runs.
   No prompt/threshold changes based on fresh holdout outcomes. If tuning follows,
   use new blind evidence to assess the changed configuration.

## Status and next gate

This proposal adds no dependency/model file and executes no AI. Requested CTO
approval is for this exact candidate/runtime family, on the laptop with synthetic
reviewed units only, followed by Tier 0 then M3. It does not approve server models,
private notes, Claude comparison, local production rollout or phone integration.
BA2 still owns host fit; Blue owns local execution/API policy; Puddlejump places
Contour. The recognition-and-human-correction slice can progress independently.

## Reading the November 5 design notes

Read zz/design-note-inquiry-draft-many-small.md and
zz/field-note-decompose-now-cloud-first-localize-later.md in Puddlejump as
requested by the CTO. The first records the agreed Ariadne per-theme fix; this
NER work makes no Ariadne change. The broader Field Note is proposed and its
owner/registry questions remain open. Its real prompt/schema/context artifacts
reinforce this unit design, but do not authorize cross-pipeline policy, blanket
consent reuse, a new registry or any cloud work for the local-only author.

No need to wait for placement to prepare the already-approved M3 draft cases and
comparator proposal. Their review gates remain. Decomposition reduces prompt
growth; it does not prove every individual unit fits. The actual per-unit token
preflight remains mandatory, independent of model/host choice. Cloud fulfillment
under a person's consent may be appropriate elsewhere; it changes nothing about
local-only refusal here.
