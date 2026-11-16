# Native Selene shadow-runner smoke — 2026-11-16

MA prepared an isolated local environment and ran this smoke at the CTO's
request (approved November 15, completed November 16). Every note here is newly
authored synthetic text. No real note, database row or private pilot directory
was opened. The run used the exact accepted two-label profile and durable pinned
GLiNER package; no model weight was downloaded or modified.

The local environment and native-smoke gates are satisfied. This is a functional
smoke, not model-quality acceptance, a held-out benchmark, a human review, a
combined ASGI serving-environment build, a Switchboard trial or host-fit evidence.

## Result

- Python 3.12.13, macOS arm64; GLiNER 0.2.30, torch 2.6.0, transformers 4.57.3.
- 37 exact runtime/validation pins plus the venv's pip bootstrap. `pip check`
  passes; metadata preflight passes. Full wheel hashes are preserved.
- Nine authored notes frozen before inference: five read and four refused.
- One refusal each: `source_too_long`, `source_word_budget`,
  `source_token_budget`, `invalid_request` (empty source).
- Ten actual candidates checked for verbatim Unicode source spans and finite raw
  scores. The original non-BMP/decomposed strings remain unchanged. Semantic
  false positives remain in the evidence; a structurally valid span is not a
  confirmed Character or Setting.
- Scripted review against predeclared synthetic gold was imported, then tallied.
  A second import preserved the first snapshot. Exported tallies contained none
  of the tested synthetic names or reviewer string.
- Model process exited 0. The driver did not import or retain torch/the model.
- macOS `(deny network*)` policy applied to the driver and inherited subprocesses;
  a loopback probe returned EPERM before inference. Python offline flags/socket
  refusal provided an additional guard. No global laptop network settings changed.
- All 30 runner unit tests pass in the new environment. Scoped runner mypy/Ruff
  and diff checks pass. No repeat of unrelated legacy M1 fixture regeneration.

Single-run timings: 18.462 seconds for the runner invocation, including 15.245
seconds in load_gliner; five inference calls ranged 0.073–0.305 seconds. Peak
self-reported model-process RSS: 1,388,969,984 bytes (1,324.625 MiB, about 1.29 GiB).
These are observations on this occupied laptop, not repeated timing ranges or
Crossroads predictions. Samples include 23 global observations over 21.519 s:
swap used 14,679.88 → 14,663.88 MiB; 13.953 MiB swap-ins, no new swap-outs in that
short interval; compressor occupied memory +96.359 MiB; physically free pages
+74.906 MiB. Other applications were active. No matched control or model-specific
swap attribution exists, and free pages are not the OS's reclaimable memory.
The sandbox denied `ps`; peak RSS comes from the child itself. Process exit
shows no retained model worker, not proof that every global swap allocation
vanished immediately.

## Failures retained and fixed

1. The first orchestration attempt failed because `ps` was sandbox-denied and
   the initial sampler did not tolerate it. The child was subsequently checked
   absent. Its partial run stays outside Git under `synthetic-smoke-1/`.
2. The second attempt reached the native loader but failed before results:
   DeBERTa fast-tokenizer conversion requires protobuf. The earlier GLiNER lock
   omitted it, although SE-P/M2 recorded protobuf 5.29.5. A setup-only diagnosis
   opened no notes and established the exception. No failed run is called success.
3. Selene's GLiNER lock now pins that previously used version (`3de1416`); Core
   preflight detects missing/conflicting protobuf before reading notes and has a
   regression test (`5b350ee7`). No accepted profile/schema/model bytes changed.
4. This complete result is `synthetic-smoke-3/`; earlier evidence and the original
   incomplete 36-package environment record were preserved rather than overwritten.

## Durable local locations

Environment root:

`~/Library/Application Support/Mixtape/Environments/selene-shadow-py312-20261115/`

Use its `venv/bin/python`. It holds `wheelhouse/`,
`requirements-shadow-v2.lock`, `requirements-shadow-hashed-v2.lock`,
`environment-record-v2.json` and the three smoke attempt directories. The date
in the directory is its setup date, not a claim all tests completed that day.
The environment uses about 1.0 GiB; wheelhouse about 107 MiB. Twenty-two wheels
were reused from local pip cache and fifteen exact wheels downloaded from public
PyPI. Installation resolved dependencies offline from that wheelhouse. No
existing Core/Switchboard/scratch environment was changed.

Model package root:

`~/Library/Application Support/Mixtape/Models/selene/gliner-small-v2.1-4e091416cf7c3481db542c2a3d26156916f3a47f/`

Complete artifact manifest was checked before and after the native run. It remains
`d00e8d3f0063e676e91dde6cbef8b42f944fda2fe195cf30e783a9cf7c81f344`.
Profile digest remains
`64b40ea0957964bb4ff23643457284e6ebefbebbe9be4d7b822f0a3c62bca837`.
Durable local storage is not a backup/sync-policy guarantee. Absolute encoder
paths make package relocation an explicit config/hash-transform operation.

## Evidence and replay

- `summary.json`: exact source identities, observed results/timings/limits and
  all installed distributions. `memory-summary.json` summarizes raw
  `host-samples.json`; global counters are not causal model measurements.
- `environment-record.json` and `requirements-shadow.lock`: final versions,
  every wheel filename/hash, and an offline `--require-hashes` rebuild lock.
- `native_smoke.py`: exact executed synthetic-only driver, hash bound in summary.
  It contains the nine invented cases and never opens externally supplied notes.
- `synthetic-notes.jsonl`, `synthetic-gold.json`, `native-results.json`: original
  authored data, predeclared labels and raw checked candidates/refusals. These
  are intentionally shareable synthetic data, not the CTO's N3/private fixture.
- `commands.json`, `tallies.json`: executed CLI records and the selected scripted
  review's output. Zero blind notes happened to be selected for this tiny fixed
  seed; the unaided-required branch is unit-tested, not demonstrated here. No
  lower-threshold run was selected. No tuning took place.
- `checksums.json`: artifact hashes, excluding that checksum file itself.

From Core's root, use a **new** output name for a repeat (the driver refuses an
existing directory). Keep the tracked runner and adapter files committed/clean;
do not reset a shared checkout to make that true.

```sh
smoke_env="$HOME/Library/Application Support/Mixtape/Environments/selene-shadow-py312-20261115"
smoke_package="$HOME/Library/Application Support/Mixtape/Models/selene/gliner-small-v2.1-4e091416cf7c3481db542c2a3d26156916f3a47f"
smoke_core="$PWD"
smoke_selene="${smoke_core%/*}/mixtape-release-selene"
/usr/bin/sandbox-exec -p '(version 1) (allow default) (deny network*)' \
  "$smoke_env/venv/bin/python" -B tools/eval/folio-ner/runs/2026-11-16-selene-native-smoke/native_smoke.py \
  --core-root "$smoke_core" --selene-root "$smoke_selene" \
  --package-root "$smoke_package" --output "$smoke_env/synthetic-smoke-NEW"
```

To rebuild the environment elsewhere on the same Python 3.12/macOS arm64 ABI,
choose a new destination, create a venv with the existing Python 3.12 interpreter,
and install from the preserved wheelhouse with:

```sh
"$new_smoke_venv/bin/python" -m pip --isolated --disable-pip-version-check install \
  --no-index --find-links "$smoke_env/wheelhouse" --require-hashes \
  -r tools/eval/folio-ner/runs/2026-11-16-selene-native-smoke/requirements-shadow.lock
```

The lock does not rebuild Python/pip themselves or provision ASGI/service deps.
Rollback is to stop using this isolated environment; no application/service was
enabled, deployed or migrated. No automatic deletion or system cleanup is included.
For the CTO's private pilot, follow `../../SHADOW_MODE.md` with a separately
chosen private input/workspace outside Git, networking off, and the real writer
reviewing. Agents must not open those private files. Scripted gold here is no
substitute for that review.
