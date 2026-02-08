# Publish + Library v1 — Pre‑Test Handoff

**Scope**
Validate new publishing semantics (no implicit placement), shelf placement via `Library`, and reader‑facing Library pages per `docs/features/writing/refinements.md` (Sections 3–4, Appendices A–F).

**Key Principles**
- Publishing creates an artifact; no placement unless explicitly selected.
- Shelf placement uses `ContentPlacement` with `channel="shelf"`.
- Default shelf is created only via explicit UI action.
- Public library page: `/@username/library`.
- Shelf page: `/@username/library/<shelfSlug>`.
- “Updated recently” uses **published timestamp**.

---

## Preconditions
- Local dev env up; frontend basePath is `/app`.
- Test user A and B exist; user A has at least one published writing piece (drafts OK).
- Run migrations (includes `writing 0004`, `publishing 0004`).

---

## Backend API Verification

### 1) Publish without placement
**Request**
- `POST /api/writing/pieces/<pieceId>/publish`
- Payload:
  - `audience: "just_me"`
  - No destinations

**Expected**
- 200 OK
- Piece status = `published`
- **No** `ContentPlacement` created

---

### 2) Publish with shelf placement
**Request**
- Create shelf first (explicit):
  - `POST /api/stackroom/libraries`
  - `tenant_type: "user"`, `tenant_id: <userA id>`, `name: "My Writing"`, `scope:"writing"`, `visibility:"public"`
- Publish:
  - `audience: "readers"`
  - `destinations.shelves: [<shelfId>]`

**Expected**
- 200 OK
- `ContentPlacement` created with:
  - `channel="shelf"`
  - `target_content_type=Library`
  - `target_object_id=<shelfId>`
  - `visibility` = shelf visibility (`public`)

---

### 3) Visibility behavior
**Setup**
- Shelf visibility `members`.
- Test as anonymous user.

**Expected**
- Shelf not visible on `/@username/library`
- Shelf page should 404/deny.

---

### 4) Public library list endpoint
**Request**
- `GET /api/stackroom/libraries/public?username=<userA>&scope=writing`

**Expected**
- Only public shelves returned
- Each item has `title`, `slug`, `summary`, `visibility`, `scope`

---

### 5) Library placements endpoint
**Request**
- `GET /api/stackroom/libraries/<libraryId>/placements`

**Expected**
- Returns placements for shelf
- Includes `piece_slug`, `piece_title`, `published_at`
- Order uses published timestamp (newest first)

---

## Frontend UI Verification

### 6) Publish dialog (Appendix A/D)
**Steps**
- Open writing editor; click Publish
- Step 1: choose **Just me**
- Publish

**Expected**
- Success message: “published and visible only to you”
- No placement added; item not visible in Library.

---

### 7) Create shelf from dialog
**Steps**
- Publish with **Readers**
- If no shelves, click “Create My Writing shelf”

**Expected**
- Shelf created
- Can select it and publish

---

### 8) Library overview page
**URL**
- `/@username/library`

**Expected**
- Displays shelf cards
- Each card shows title + summary + visibility badge
- “Updated recently” uses published timestamp

---

### 9) Shelf page
**URL**
- `/@username/library/<shelfSlug>`

**Expected**
- Title, summary, optional body
- Ordered list of pieces with title + published date

---

## Regression Checks
- Group publish still works via `Publish…` dialog (explicit).
- No “Publish Now” implicit feed placement in Draft Room / editor.

---

## Notes / Known Constraints
- Newsletter option intentionally deferred (no UI).
- Unlisted shelves are not shown in library overview, but should be accessible via direct URL.
