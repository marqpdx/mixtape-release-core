# Publishing v1 Backend Test Plan

Scope: Validate PUBLISH_IMPLEMENT.md §6 (v1) changes:
- WritingVersion `sequence_no` + `version_label`
- ContentPlacement DB CheckConstraints
- Publish path creates artifact → placements (locked by default)
- Public read paths resolve artifacts (placements → artifacts)

Assumptions:
- Local DB, no existing production data.
- Auth user can publish a WritingPiece they own.
- Publish endpoint: `POST /api/writing/pieces/{id}/publish` (WritingPiecePublishAndPlaceView).
- Public view endpoints:
  - `GET /api/writing/pieces/view/{slug}`
  - `GET /api/groups/{group_slug}/writing/{piece_slug}`

## Preconditions (setup)
- Create a user `u1` with known password.
- Create a `WritingPiece` owned by `u1`, with:
  - title, excerpt, body_json
  - status draft
  - sponsor_content_type = User (or Group if testing group feed)
- Ensure `WritingPiece.is_empty == False`.
- Have at least one destination ready:
  - Personal feed (member)
  - Optional: Group feed (create Group and make `u1` admin).

---

## A) DB Constraints: ContentPlacement (hard requirements)

### A1. Invalid: follow_updates=False + no lock
Steps:
1) Create ContentPlacement with `follow_updates=False` and no locked_artifact fields.
Expected:
- DB error (IntegrityError), not saved.

### A2. Invalid: follow_updates=True + lock set
Steps:
1) Create ContentPlacement with `follow_updates=True` and locked_artifact fields set.
Expected:
- DB error (IntegrityError), not saved.

### A3. Valid: follow_updates=True + lock NULL
Steps:
1) Create ContentPlacement with `follow_updates=True` and no lock fields.
Expected:
- Placement saved successfully.

### A4. Valid: follow_updates=False + lock set
Steps:
1) Create ContentPlacement with lock fields set and `follow_updates=False`.
Expected:
- Placement saved successfully.

---

## B) WritingVersion: sequence + label

### B1. First publish creates sequence_no=1
Steps:
1) Publish a draft piece (see section C).
Expected:
- WritingVersion created with `sequence_no = 1`, `version_label = "1"`.

### B2. Second publish increments sequence_no
Steps:
1) Modify draft content.
2) Publish again.
Expected:
- New WritingVersion created with `sequence_no = 2`, `version_label = "2"`.
- `WritingPiece.current_version_no` updated to 2.

---

## C) Publish path: artifact → placements

### C1. Publish creates WritingVersion first, then placements
Steps:
1) Publish with destinations `{ members: [user_id] }` or personal feed.
Expected:
- WritingVersion exists with `kind="release"`.
- ContentPlacement created with:
  - `locked_artifact_*` fields set to that version
  - `follow_updates = False` (default)
  - `visibility = public` unless scheduled

### C2. Scheduled publish creates version + placement with scheduled visibility
Steps:
1) Publish with `scheduled_for` set.
Expected:
- WritingVersion created.
- ContentPlacement created with `visibility="scheduled"`.
- WritingPiece status = `scheduled`.

---

## D) Public read path uses artifacts (placements → artifacts)

### D1. Public view returns artifact body_json
Steps:
1) Publish piece with a known body_json version.
2) Change WritingPiece.body_json directly (simulate draft change after publish).
3) Call `GET /api/writing/pieces/view/{slug}`.
Expected:
- Response `body_json` matches WritingVersion (artifact), NOT the updated draft.

### D2. Group view returns artifact body_json
Steps:
1) Publish piece to group feed placement.
2) Change draft body_json.
3) Call group view `GET /api/groups/{group_slug}/writing/{piece_slug}`.
Expected:
- Response body_json matches WritingVersion (artifact), NOT the draft.

---

## E) Regression checks

### E1. Draft list still works
Steps:
1) Create or edit a draft via working copy.
2) Query drafts list for sponsor.
Expected:
- Draft appears with correct title/excerpt.

### E2. Sponsor placements list returns display payload
Steps:
1) Publish a piece.
2) Call placements list (SponsorPlacementsListView).
Expected:
- Response includes display metadata (title, excerpt, body_json) from artifact.

---

## Notes / Edge cases to watch
- If publish payload omits title, endpoint should reject (400).
- If no destinations are supplied, endpoint should reject (400).
- If follow_updates is passed true, placement must be unlocked (constraint enforced).

---

## Deliverables to capture
- Screenshots or response JSON showing artifact body_json returned in public views.
- DB rows for WritingVersion and ContentPlacement confirming `sequence_no` and lock fields.
