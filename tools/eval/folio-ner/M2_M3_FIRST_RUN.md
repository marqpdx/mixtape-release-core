# Local NER first run — M2 and GLiNER's M3 baseline

2026-11-04 · NER Eval · laptop arm64 / 16 GiB RAM

The CTO advanced local work for an author who cannot use cloud AI. Both encoder
models ran locally, with network disabled for inference. No production dependency,
privacy policy, capability registration or client feature changed. The source
fixtures are the 21 reviewed synthetic cases; no private note or Claude call.

## Status and provenance

- M2 local comparison executed, code pinned at core 103ed442. M2 is **partial**:
  no measured Claude baseline and no formal matrix filing yet.
- M3 GLiNER containment baseline executed, code pinned at core 0551766f. M3 is
  **partial**: local-generative and Claude comparators remain unrun.
- 44 harness tests pass. First Tier 0 load failed for missing protobuf; installing
  pinned protobuf 5.29.5 fixed it. Both models then found Alice/London coherently.
  Encoders have no chat-template stage. Fiction task sanity ran before corpus scoring.
- The initial sandbox spaCy tuning run succeeded, then OpenMP aborted contrast
  because shared memory was blocked. No score was substituted for that failure.
  All eight reported M2 model/split runs were repeated outside the sandbox, with
  OMP_NUM_THREADS=2 and model networking disabled.
- All artifacts are under runs/2026-11-04-local-first/. M2 directories contain
  raw predictions, contract responses, error lists, per-type scores and metadata.
  M3 directories contain supplied-span units, sentences, expected/predicted labels,
  raw model evidence and confusion counts. Models/venv stay outside git.
- Raw package lock, exact download sources/hashes and Tier 0 evidence are committed
  beside the runners. No thresholds or labels were tuned on held-out results.

## M2 exact mention spans

Rules remain cue-only and emit no name mentions. Both model adapters include that
unchanged baseline; cue and mention metrics remain separate. spaCy PERSON maps
provisionally to Character, GPE/LOC/FAC to Setting, with no Scene mapping. GLiNER
uses fixed labels character/setting/scene, threshold 0.5 and flat_ner=False.
Scores are uncalibrated. Optional baker handling is unchanged.

| Split | Required gold mentions | spaCy TP / FP / FN | GLiNER TP / FP / FN |
| --- | ---: | --- | --- |
| tuning | 6 | 1 / 0 / 5 | 6 / 3 / 0 |
| contrast | 5 | 2 / 4 / 3 | 5 / 5 / 0 |
| paraphrase | 10 | 5 / 1 / 5 | 10 / 1 / 0 |
| holdout | 11 | 6 / 1 / 5 | 11 / 3 / 0 |

The five holdout cases yield precision/recall/F1 of .857/.545/.667 for spaCy and
.786/1.000/.880 for GLiNER. This tiny synthetic sample supports trying GLiNER as
provisional mention evidence, not declaring general accuracy or adopting it for
semantic interpretation. Exact spans include duplicate/overlapping predictions:
no post-processing trimmed articles or possessives or hid errors. GLiNER's
Fiction sanity also proposed the title Jackalope as a Character and overlapping
station spans, retained in m2-tier0.json.

This dataset's mention gold covers Character/Setting names. Scene interpretation
is annotated separately as Shape judgements; these mention scores do **not**
measure Scene narrative extraction. GLiNER's extra Scene mention proposals are
counted as false positives in this narrower mention contract, not a blanket
judgement of its Scene capability.

## M3 supplied-mention baseline

A deterministic sentence selector preserves original offsets. GLiNER labels the
sentence; the smallest predicted span containing the supplied mention wins,
otherwise none. Required gold mentions provide oracle input locations, and
reviewed traps supply negative none units. Optional mentions are excluded.
The classifier never receives the expected type; these are classification-only
results, not end-to-end detection scores or an independent generative reading.

| Split | Correct / supplied units |
| --- | --- |
| tuning | 6 / 6 |
| contrast | 9 / 14 |
| paraphrase | 10 / 10 |
| holdout | 13 / 13 |

The contrast negatives expose the key limitation: five of nine none cases were
mistakenly labelled (three Characters, one Setting, one Scene). A candidate whose
name is detected is not necessarily fictional. M3 needs reviewed positive Scene
classification units as well; the current derived units do not establish that
class. No semantic replacement is adopted from this run.

## Resource observations

CPU inference, two torch threads. Mean per-note warm inference on these short
samples: spaCy .003–.006 seconds; GLiNER .038–.074 seconds. Peak process RSS:
spaCy 811–880 MiB, GLiNER 1455–1519 MiB. These include the Python/library process;
this is not the size of the weight file. Both models loaded together peaked near
1.38 GiB in the separate Tier 0 process. Environment plus model files used about
1.35 GiB disk before result artifacts. RAM headroom, concurrent service load,
cold starts and production fit still need M4; no server-fit claim follows from
laptop numbers. No paid server was provisioned.

## Next for the non-cloud author

1. Complete M3 with a pinned, small local generative comparator and Tier 0 sanity,
   keeping its exact classification unit separate from full narrative composition.
2. Review false positives/negative handling and positive Scene cases before
   choosing a local step. Any changed labels, threshold or prompt need a new run;
   the now-inspected holdouts cannot serve as fresh blind evidence for tuning.
3. Propose an explicit local Heddle/Switchboard/Inkwell adapter and versioned
   Strategy. Local unavailable must remain visible; no cloud fallback for this author.
4. Measure server fit and obtain the separate privacy-facing rollout decision.
   The current Folio phone reading still requires lifecycle/routing/client wiring.

Claude is expected to be useful but has not been measured as this baseline;
no result is inferred from that expectation. This first run accelerates evidence,
not production adoption or a promise of a wholly local narrative reading.
