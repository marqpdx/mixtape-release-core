# M3 next comparator — Qwen2.5-1.5B approval proposal

2026-11-06 · NER Eval · metadata fetched only; no weights downloaded or run

The approved 0.5B comparator passed execution/structural Tier 0 but gave zero
valid correct results on the 16 seed units. The CTO's handoff specifically asks
for a 1.5B proposal in that event. This is the proposal, not authorization to run.

## Exact artifact

- Publisher: `Qwen/Qwen2.5-1.5B-Instruct-GGUF`.
- Revision: `91cad51170dc346986eccefdc2dd33a9da36ead9`.
- File: `qwen2.5-1.5b-instruct-q4_k_m.gguf`.
- Size: **1,117,320,736 bytes** (~1.12 GB decimal / 1066 MiB).
- SHA-256: **6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e**.
- Licence: Apache-2.0 per publisher metadata; retain pinned LICENSE and README
  with an approved future download. Publisher metadata is archived with the run.

Sources: [publisher API metadata](https://huggingface.co/api/models/Qwen/Qwen2.5-1.5B-Instruct-GGUF?blobs=true)
and [pinned artifact](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/blob/91cad51170dc346986eccefdc2dd33a9da36ead9/qwen2.5-1.5b-instruct-q4_k_m.gguf).

## Proposed scope

Same isolated laptop runtime llama-cpp-python 0.3.15 and fixed M3 prompt,
vocabulary, schema, evidence validator and CPU profile (2 threads, 0 GPU layers,
8192 context, 256 output, temperature 0, seed 0). Verify exact file hash, actual
embedded chat template and token budget. Record the larger model's real RAM and
time instead of estimating from the weight file. It is a bounded span-role task,
not a full Fiction reader. The cached runtime's original build flags/llama.cpp
commit remain unavailable; report that provenance limit rather than invent them.

Tier 0 first, then the same approved 16-unit seed set without prompt changes.
These cases are now seen by the experimenter; call this a same-task model
comparison, not new blind evidence. Leave the three historical Scene replay
grains unchanged. Obtain new independent cases for later tuning claims.

No server, paid VPS, production dependency, private note, cloud call, application
routing or phone change. A specific CTO go-ahead is needed before downloading or
running this artifact. If approved, only the artifact identity changes in the
runner, with its own recorded commit and Tier 0; no hidden prompt repair.
