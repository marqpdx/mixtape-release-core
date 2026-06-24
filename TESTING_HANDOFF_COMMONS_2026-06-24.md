# Testing Hand-off — Commons CM-0 through CM-4 (ADR-0049)

**Date:** 2026-06-24
**Built by:** Claude Code (dev agent), CTO: marqpdx
**Scope:** Backend checkpoints CM-0–CM-4 in `mixtape-release-core`, migrated
locally (incremental apply only — see Open Items). `npx manage.py check`
clean. No automated tests exist yet for `relations` or the new `tapestry`
app — this is what needs covering.

Status docs: `../puddlejump/decisions/commons-adr/commons-status.md`,
`../puddlejump/decisions/commons-adr/commons-adr.md`.

---

## What was built

**CM-0 — `tapestry` app + `Place` stub** (`app/tapestry/`)
- New Django app, registered in `INSTALLED_APPS` (`app/mixtape/settings/base.py`).
- `Place(BaseModel)`: `name`, `latitude`, `longitude`, `address` — all the
  GIS fields are nullable/optional except `name`. Full Tapestry (search, map
  rendering, dedup) is explicitly out of scope (D17).
- Migration: `tapestry/migrations/0001_initial.py`.

**CM-1 — `Leaf` extended fields** (`app/writing/models.py`)
- Added `place` (FK to `tapestry.Place`, nullable), `occurred_at`
  (nullable), `state` (`open`/`closed`, default `open`), `library_only`
  (default `False`), `feeling_state`/`intent_primary`/`intent_secondary`
  (reserved, not exposed anywhere yet — D14/D15).
- Migration: `writing/migrations/0026_leaf_feeling_state_leaf_intent_primary_and_more.py`.
- **Not enforced in code yet**: OQ-5 says `place` is required when
  `state` transitions to `closed` with `library_only=False`. That
  enforcement is service-layer work for CM-7+ (the composer), not added
  here — CM-1 is the migration only.

**CM-2 — `LeafEntry` model** (`app/writing/models.py`)
- `kind` (text/image/voice), `position`, `body_text`, `body_json`,
  `image_file`/`audio_file`, `shared` (default `True`, trim-for-sharing).
- **Spec deviation, deliberate**: the ADR's draft text named
  `stash.StashFile` for `image_file`/`audio_file`. No `stash` app exists in
  this codebase. Used `files.StoredFile` instead — the same model `Leaf`
  itself already uses for `audio_file`/`image_file`. Worth double-checking
  this FK target resolves correctly in any test fixtures.
- Migration: `writing/migrations/0027_leafentry.py`.

**CM-3 — `commons` domain `RelationshipType` seeds** (data migration)
- `relations/migrations/0008_add_commons_relation_types.py` — adds 6 rows:
  `presence`, `continues`, `origin`, `context`, `continuation`, `parallel`,
  all `domain="commons"`.
- **Spec deviation, deliberate**: the ADR table writes these as
  `commons/presence`, `commons/continues`, etc. — that's `domain/slug`
  display format from `RelationshipType.__str__`, not the literal slug
  value (`SlugField` rejects `/`). Bare slugs match the existing
  `commons`-domain convention (`founded-by`, `located-in`, etc. in
  `0002_seed_relationship_types.py`).
- Migration has a reverse op (`remove_commons_types`) — **not yet tested
  that `migrate relations 0007` cleanly unwinds it.**
- `commons/continues` has `allows_position=True` (Thread sequencing);
  `commons/presence` has `uses_lifecycle=True` (authored → acknowledged,
  OQ-4); the other four have `uses_lifecycle=False`.

**CM-4 — Thread metadata convention** (`app/relations/service.py`)
- No schema change — Thread has no model (D9/D10 say identity lives in
  `Relationship.metadata`). Added to `RelationshipService`:
  - `THREAD_ID_KEY` / `THREAD_TITLE_KEY` / `THREAD_CLOSED_KEY` constants.
  - `continue_thread(from_leaf, to_leaf, created_by, position, thread_id=None, thread_title="")`
    — creates a `continues` Relationship. `thread_id=None` mints a new UUID
    (this is the Close-time "Begin" case).
  - `is_thread_closed(thread_id)`, `get_thread(thread_id)` (ordered by
    `position`, `created_at`), `close_thread(thread_id)` (flips
    `thread_closed=True` on every Relationship in the thread; raises
    `ValueError` if `continue_thread` is later called against a closed
    `thread_id`).
- **Open design gap, not papered over**: OQ-3 ("Thread identity model — may
  need a lightweight `LeafThread` model") is still open in
  `commons-status.md`, gated "before Thread view (Phase 2)." Consequence:
  a single Leaf that is never `continue_thread`'d into a second Leaf has no
  Thread identity at all — there's no "Begin a Thread with just this one
  Leaf" persistence. That's intentional given OQ-3 is unresolved, not a
  bug — but it means the Close-time "Begin" UX (CM-10) can't actually
  register a Thread until a *second* Leaf joins it. Flag this back to
  Puddlejump/design if CM-10's UX assumes otherwise.

**Not in this batch:** CM-0b (renaming `app/commons/CommonsItem` →
something like `Atlas`, auditing production data) is tracked separately in
`commons-status.md` and was deliberately deferred — it's a riskier,
independent operation (live app/model rename) that wants its own
go/no-go, not bundled into CM-0–CM-4.

---

## What needs testing

1. **Fresh-DB migration test.** Everything above was applied incrementally
   on an already-running local DB. Nobody has run `migrate` from zero on a
   clean database with these four migrations in the mix — please verify a
   full `migrate` from scratch succeeds (dependency ordering:
   `tapestry.0001` has no deps; `writing.0026`/`0027` depend on
   `tapestry.0001` implicitly via the `place`/`StoredFile` FKs but Django
   migration autodetection should have captured that — confirm).
2. **Reverse migration.** Unapply `relations.0008` (`migrate relations 0007`)
   and confirm the 6 seeded `RelationshipType` rows are cleanly removed and
   nothing else references them yet (nothing does, since no caller exists
   until CM-7+).
3. **Model defaults.** New `Leaf` instances: `state == 'open'`,
   `library_only == False`, `place`/`occurred_at` are `None`. New
   `LeafEntry`: `shared == True`.
4. **`RelationshipService` thread methods** (no existing test file for
   `relations` app — this needs new tests written, not just exercised):
   - `continue_thread(thread_id=None)` mints a new `thread_id`, persists
     `thread_title`, `thread_closed=False`.
   - `continue_thread(thread_id=<existing>)` carries the same `thread_id`
     forward; `position` increments as expected; `get_thread()` returns
     rows ordered by `position`.
   - `close_thread()` sets `thread_closed=True` on every Relationship in
     the thread; a subsequent `continue_thread(thread_id=<closed>)` raises
     `ValueError`.
   - `is_thread_closed(None)` returns `False` (no thread yet) rather than
     erroring.
5. **`commons/presence` lifecycle.** Confirm `RelationshipService` (or a
   thin wrapper) can move a `presence` Relationship from `authored` to
   `acknowledged` via the existing generic `acknowledge_relationship`
   method — it wasn't given commons-specific tests, but the lifecycle
   field is generic so it should work as-is. Worth a smoke test since this
   is OQ-4's whole mechanism.
6. **`files.StoredFile` FK substitution** (CM-2's spec deviation above) —
   confirm `LeafEntry.image_file`/`audio_file` actually resolve against
   real `StoredFile` rows in a fixture/factory, not just that the
   migration applies.

## Out of scope for this test pass

- Anything CM-5 onward (Bridge creation hooks, Loom sweep stub) — not built.
- CM-7–CM-15 (frontend composer/Commons views) — blocked on this batch
  landing, not started.
- CM-0b (CommonsItem rename) — not built, separate decision.
- OQ-3 (Thread identity for a lone, not-yet-continued Leaf) — open by
  design, see CM-4 note above.

---

## Related mobile-side changes (separate repo: `mixtape-release-frontend`, `apps/mobile`)

Not part of CM-0–CM-4, but landed same session, same testing pass is a
reasonable place to also flag these for on-device verification:

1. **Tab bar icons** (`src/navigation/AppNavigator.tsx`) — back to original
   Ionicons (`book`/`image`/`chatbubble`/`hammer`) for Notebook/Storyline/
   Connect/Build; Lists changed from a Lucide `sticky-note` (stroke-width
   mismatch against Ionicons) to Ionicons `list`. `lucide-react-native` and
   `react-native-svg` dependencies removed — confirm nothing else needed
   them (checked at the time, but worth a fresh `grep` before shipping).
2. **Cursor refocus after voice send** (`CaptureDock.tsx`,
   `handleSubmitVoice`) — text input should regain focus immediately after
   a voice note finishes uploading, same pattern as text-submit. Needs a
   real on-device check (rapid-typing-after-voice-note flow).
3. **Transcription polling unified** — three separate poll implementations
   (`SeedNotebook.tsx`'s voice-Seed refresh, `useUploadIntroVoice.ts`,
   `useInitiativesVoiceInput.ts`) now share
   `src/services/polling/pollWithBackoff.ts`, schedule `[3000, 6000, 10000,
   16000, 24000]`ms (previously 5s/24s, fixed 3s, and fixed 2s×30 attempts,
   respectively). Needs on-device testing across all three flows to confirm
   transcription still completes within the new cadence and the wait
   "feels" shorter, which was the original ask.
4. `npx tsc --noEmit` clean at time of writing; CTO reports lint clean on
   current build run.
