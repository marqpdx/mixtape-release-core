# Selene SE-2 — offline resolver prerequisite and Contour activation review

## Activation completed — 2026-11-11

CTO approved activation after Blue/Puddlejump review. MA applied the exact reviewed
patch plus the requested manifest update line in Puddlejump `e8a2664f —
feat(contour): activate reviewed Folio recognition definitions (0.4.7)`.
Core `d003b2a2 — feat(heddle): pin activated Contour recognition bundle (0.4.7)`
regenerated the shipped bundle from that committed canon. The bundle records
source commit `e8a2664f` and digest
`81d0277bf554ae228be38c8487b81709cf26a1546013f91662f231f3da8ebc04`.

The 40 named database-free regressions below pass, including the Argus payload
format regression in `test_schema_registry`; Django system checks and the canonical
bundle drift check pass. The first post-activation test run exposed pre-activation
fixture assumptions (omitted shared definitions, directories assumed absent,
recognition assumed unselected, and current descriptors copied over retained
ones). The bundle commit updates those two fixture modules; runtime resolver and
generator behavior did not need changing. All ten retained 0.1.0 canonical files
were byte-checked against their original contents; the activated schemas, shared
definitions and recognition Strategy match the reviewed proposals exactly.

No database-backed lifecycle/migration suite, static type check, model inference,
host-fit/firewall check or live trial was run for activation. No recognition
consumer/capability was enabled. SE-2 remains in progress. Push Puddlejump and Core
together so remote drift checks see the same canon. The review package below is
the historical, unapplied preparation evidence; do not reapply its patch to 0.4.7.

## Original review package — prepared 2026-11-10

Prepared by MA, 2026-11-10. **Review only: canonical Contour is not activated.**
The CTO approved resolver implementation and preparation of this activation
proposal after the SE-2 dependency check. Blue/Puddlejump review and canonical
activation still precede consumer recognition wiring.

## What changed in Core

- `heddle.bundle.schema_validator` uses a local `referencing.Registry` built from
  pinned schema resources. Missing URN, HTTP and file references fail without
  retrieval; generation preflights even references in unused branches.
- UUID and ordinary timezone-aware date-time validation is explicit. It does not
  depend on optional jsonschema format extras being installed. Date-time checking
  accepts ordinary server timestamps, including fractional seconds and offsets;
  leap-second timestamps are not supported. The proposed provenance schema also
  requires UTC, enforced by its own pattern.
- Heddle's worker output validator and the existing Fiction findings validator use
  that same registry/format-aware validator. This is schema validation only, not
  verification of the claimed actor, model execution, ownership or exact source.
- The generator supports explicitly selected top-level manifest `schema_definitions`
  with `id`, `version`, `schema_file`. Their exact URNs must match and their files
  must be on the shared shelf. It can select the distinct recognition Strategy
  only when present in the active canonical manifest. `_proposed/` is excluded.
- Archived `.shape.yaml` descriptors are bundled alongside archived schemas.
  The existing composed-reading Strategy selects its exact retained 0.1.0
  descriptor if the current shelf advances; it refuses missing versions and does
  not silently consume newer cue metadata.
- Today's `contour_bundle.json` is unchanged and reconstructs exactly from canon.
  No new schema is active, registered or shipped in the runtime bundle.

## Proposed activation

`contour-activation.patch` is an **unapplied** unified diff for the Puddlejump repo.
It proposes library version 0.4.7 from the reviewed 0.4.6 baseline:

1. Preserve Character/Setting 0.1.0 schemas, descriptors and guidance byte for byte
   as new files under `writing/versions/`; nothing is deleted or renamed.
2. Copy the exact proposed 0.2.0 schemas and two shared definitions into their
   active shelf paths, plus the separate recognition Strategy and prose.
3. Update current metadata and guidance for provenance and conditional confidence.
4. Select shared definitions and recognition in the canonical manifest and update
   shelf documentation. The composed Strategy remains 0.1.0.

This is not authorization to apply the patch, change production, register a
capability, regenerate the shipped bundle or build the phone. Puddlejump should
record the actual acceptance/activation in the proposed record's Headnote when
approved. If canon advances first, re-review the diff rather than applying an old
version bump blindly. The baseline commit and retained hashes are recorded in
`activation-review.json`.

## Reproduce the review

From Core, using its existing environment, no package installation:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=app env/bin/python \
  tools/review/selene-se2/prepare_activation.py \
  --release-root /path/to/release --output-dir /tmp/selene-contour-review
```

The script reads selected canonical inputs and exact proposed schema files only,
reconstructs a proposed tree in scratch, verifies old-file hashes and both schema
versions, tests real draft provenance/conditional confidence/UUID/UTC date-time,
and emits a diff, review report and scratch bundle. It refuses socket/DNS access.
It never writes to canonical Contour or the shipped Core bundle. The generated
review bundle remains scratch evidence, not a production artifact.

From Puddlejump, review without applying:

```sh
git apply --check /path/to/core/tools/review/selene-se2/contour-activation.patch
```

## Validation

Passed 40 database-free tests:

```sh
cd app
PYTHONDONTWRITEBYTECODE=1 ../env/bin/python manage.py test \
  heddle.tests.test_bundle_generation heddle.tests.test_schema_registry \
  heddle.tests.test_ordered.BundleTests folio.tests.test_fiction_strategy \
  --settings=mixtape.settings.test --noinput --verbosity=1
```

Django system checks passed. An additional existing Argus payload regression confirms valid timestamps still pass and malformed timestamps now fail. The scratch activation accepted seven valid actual
schema examples and rejected twelve invalid ones. Retained original files matched
their hashes, old composed-reading cues still worked, and `git apply --check`
passed. Published 0.1.0 schemas and the shipped runtime bundle are unchanged.

Not run: database-backed lifecycle/migration suites, static type checking,
recognition integration/model inference, actual-host firewall/fit verification or
production traffic. No model/package download, credentials, deployment or network
provisioning is part of this work.

## Remaining SE-2 work

Blue/Puddlejump must review the resolver and activation proposal. After canonical
activation and regeneration of the pinned bundle, build recognition's actual
child ActionRun/local Heddle step, Selene GLiNER adapter/endpoint, registered
Switchboard routing and local-only policy guards, and the writer-authorized
`Folio.local_only` migration/update surface. Preserve source/context identity,
Unicode spans and raw numeric evidence separately from canonical Sightings. Mobile
owns the writer UI through the CTO-mediated handoff. None of those integrations is
claimed complete by this prerequisite commit; SE-2 remains in progress.
