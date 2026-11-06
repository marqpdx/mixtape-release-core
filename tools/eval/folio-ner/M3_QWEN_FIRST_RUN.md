# M3 local Qwen comparator — first measured unit

2026-11-06 · NER Eval · laptop only

CTO approval: November 5 headnote in
`puddlejump/zz/_handoffs/handoff-2026-11-05-mobile-folio-contract-decided-next.md`.
Juno is corrected to “pockets their hands”; all 16 seed cases were frozen and
committed before inference. Existing M1/M2/M3 GLiNER results are unchanged.

## Result

| Split | Units | Valid correct | Invalid output/evidence | Abstained |
|---|---:|---:|---:|---:|
| Review | 4 | 0 | 1 | 0 |
| Contrast | 4 | 0 | 3 | 0 |
| Fresh holdout | 8 | 0 | 5 | 0 |
| Total | 16 | 0 | 9 | 0 |

Every raw response chose `writing.scene`. Seven responses were structurally and
quotation-valid but assigned Scene to a non-Scene target. Nine failed required
fields, evidence shape or quotation occurrence checks. Some Scene answers had
the right label but invalid evidence/envelope; do not count them as usable.
No abstention or invalid result was removed from the denominator. There were no
output-budget terminations: every call finished with `stop`.

**Not suitable for this span-role unit with this fixed prompt and runtime.**
This is evidence about one small quantized model/configuration, not a verdict on
local semantic interpretation or all Qwen models. It does not establish that the
writer needs a stricter speaking grammar. The prompt includes the three complete
selected Shape definitions and their disambiguation; this model failed even on
explicit cases. A last-definition bias is a hypothesis, not a demonstrated cause.

The positive Scene targets, names, settings and external collaborators share the
same fixed task. None of these outcomes was used to revise it or rerun a case.
These holdouts are now seen; any prompt tuning needs new blind evidence.

## Tier 0, resource and identity evidence

- Exact model: `Qwen/Qwen2.5-0.5B-Instruct-GGUF`, revision
  `9217f5db79a29953eb74d5343926648285ec7e67`,
  `qwen2.5-0.5b-instruct-q4_k_m.gguf`, 491,400,032 bytes. SHA-256 matched
  `74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db`.
- Isolated Python 3.14.3, llama-cpp-python 0.3.15, CPU inference, two threads,
  n_gpu_layers=0, context 8192, max output 256, temperature 0, seed 0.
- Tier 0: raw capital completion, embedded GGUF template arithmetic, and a
  structure/evidence-valid review answer all passed. **The review answer chose
  the wrong role.** Tier 0 checks execution/structure, not semantic fitness.
- Embedded GGUF Jinja template is rendered directly and retained in producer
  metadata and every actual prompt. No guessed chat-format fallback.
- Input range 1008–1049 tokens; explicit 256 output + 32 control-token reserve.
  No truncation or backend substitution. Mean scored unit 4.79 s, range
  3.01–6.70 s; load 23.59 s; process peak RSS 1,094,696,960 bytes (~1044 MiB).
  Host contention/cold caches can affect these laptop figures; not a VPS fit claim.
- Initial pre-initialization native system-info probe crashed; isolated import
  and post-load system info succeeded. Preserve as a harness probe incident.
- pip reused a cached native wheel, so CMAKE_ARGS did not rebuild it. Observed
  compiled features include Metal/Accelerate, while inference requested zero GPU
  layers. Original compiler/build flags and vendored llama.cpp commit are not
  available from that wheel. Native library SHA-256s, full pip freeze and observed
  system info are retained; build-from-source reproducibility remains a limit.

## Audit and scope

`runs/2026-11-06-qwen-0.5b/` contains exact corpus, full release-local Contour
bundle, selected vocabulary projection, schema, prompts, outputs, exact source
evidence checks, per-split confusion, model metadata, native library hashes,
runtime install log and publisher metadata for the next proposal. Model weights
and temporary environments are outside git. The selected vocabulary retains
id/version, description, representation, all cues and all disambiguation for the
three Shapes, derived from the verified pinned bundle.

One generation judges one supplied target. Deterministic preparation, evidence
checks and scoring are separate. No whole-Folio interpretation, aliases, Entity
creation, application ActionRun, server install, production dependency, private
N3 note or cloud comparator was involved. This is a standalone eval, not a
registered Heddle capability. Native-call signal timeout is best-effort and may
not interrupt C code immediately; no measured unit reached it.

The three historical Scene replay references keep their approved grain, but were
not executed in this first 16-unit comparator run. The old GLiNER oracle corpus
differs: do not present these figures as a controlled same-input head-to-head.
M3 remains partial; no Claude comparison or production selection is implied.

## Next

Per the handoff, propose exact Qwen2.5-1.5B Q4_K_M before downloading/running it
(see `M3_QWEN_1_5B_PROPOSAL.md`). Keep the same fixed unit/prompt/schema, report
these already-seen cases as a same-task comparison, then obtain fresh blind
evidence before any tuning or production claim. In parallel, recognition plus
human correction/confirmed Folio Dictionary does not require this model to pass.
