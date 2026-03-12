# Puddlejump — Security & Fidelity Fixes Pre-Test Handoff

**Scope**
Validate all security fixes, access control additions, and new endpoints introduced during the puddlejump fidelity + security pass (2026-03-11). This covers: canon view access control (S1), bundle validation hardening (S2/S3/CI-2/CI-3), canon approval permission (D4), new library status endpoint (D5), and group library access in utility views (S5).

**Key Principles**
- All canon endpoints require authentication AND library ownership/membership.
- Unauthorized access returns **404** (not 403) — no information leak about resource existence.
- Path traversal attempts in sync upload return 400.
- Bundle size validation measures actual bytes, not zip metadata.
- Canon approval requires Group Admin or Owner role (not just any authenticated user).
- The new `GET .../libraries/{id}/status` endpoint requires library access.

---

## Preconditions

- Local dev env running.
- Two test users: `user_a` (library owner) and `user_b` (no access).
- A Group with `user_a` as owner and a separate Group library. `user_b` is not a member.
- A third test user `user_member` who is an active member (but not admin) of a Group library.
- `user_a` has a personal Puddlejump library with at least one ingested SourceFile.
- Get library IDs via:
  ```
  GET /api/stackroom/puddlejump/personal   (as user_a)
  ```
  Note `id` as `<PERSONAL_LIB_ID>` and obtain the SourceFile ID from `items[0].source_file_id` as `<SOURCE_FILE_ID>`.

---

## Section A — Canon View Access Control (S1)

### A1) Version list — own library

**Request**
```
GET /api/stackroom/source-files/<SOURCE_FILE_ID>/versions
Authorization: Bearer <USER_A_TOKEN>
```

**Expected**
- 200 OK
- `{"versions": [...]}`

**Verify**
- [ ] Returns version list (may be empty array if no versions submitted yet)

---

### A2) Version list — another user's file

**Request**
```
GET /api/stackroom/source-files/<SOURCE_FILE_ID>/versions
Authorization: Bearer <USER_B_TOKEN>
```

**Expected**
- 404 Not Found
- `{"error": "Not found"}`

**Verify**
- [ ] User B cannot enumerate another user's version history
- [ ] Response is 404, not 403

---

### A3) Diff — unauthorized

**Request**
```
GET /api/stackroom/source-files/<SOURCE_FILE_ID>/diff
Authorization: Bearer <USER_B_TOKEN>
```

**Expected**
- 404 Not Found

---

### A4) Checkout — unauthorized

**Request**
```
POST /api/stackroom/source-files/<SOURCE_FILE_ID>/checkout
Authorization: Bearer <USER_B_TOKEN>
```

**Expected**
- 404 Not Found

---

### A5) Checkin — unauthorized

**Request**
```
POST /api/stackroom/source-files/<SOURCE_FILE_ID>/checkin
Authorization: Bearer <USER_B_TOKEN>
```

**Expected**
- 404 Not Found

---

### A6) Export — unauthorized

**Request**
```
GET /api/stackroom/libraries/<PERSONAL_LIB_ID>/export
Authorization: Bearer <USER_B_TOKEN>
```

**Expected**
- 404 Not Found

---

### A7) Library status — unauthorized

**Request**
```
GET /api/stackroom/libraries/<PERSONAL_LIB_ID>/status
Authorization: Bearer <USER_B_TOKEN>
```

**Expected**
- 404 Not Found

---

### A8) Canon views — unauthenticated

**Request**
```
GET /api/stackroom/source-files/<SOURCE_FILE_ID>/versions
(no Authorization header)
```

**Expected**
- 401 Unauthorized

---

## Section B — Bundle Import Validation (S2 / S3 / CI-2 / CI-3)

### B1) Import — valid small bundle passes

**Request**
```
POST /api/stackroom/puddlejump/import
Authorization: Bearer <USER_A_TOKEN>
Content-Type: multipart/form-data

file: <valid bundle zip with 1 .md file, correct puddlejump.json and PUDDLEJUMP.md>
```

**Expected**
- 200 OK
- `{"status": "completed", ...}`

---

### B2) Import — bundle exceeds 300 files

**Request**
```
POST /api/stackroom/puddlejump/import
Authorization: Bearer <USER_A_TOKEN>
Content-Type: multipart/form-data

file: <zip with 301 .md files in Documents/>
```

**Expected**
- 400 Bad Request
- `{"valid": false, "errors": [{"field": "file_count", ...}]}`

**Verify**
- [ ] Error message references 300-file limit

---

### B3) Import — non-markdown file in Documents/

**Request**
```
POST /api/stackroom/puddlejump/import
Authorization: Bearer <USER_A_TOKEN>

file: <zip containing Documents/notes.txt>
```

**Expected**
- 400 Bad Request
- `{"valid": false, "errors": [{"field": "file_format", ...}]}`

---

### B4) Import — missing puddlejump.json

**Request**
```
POST /api/stackroom/puddlejump/import
Authorization: Bearer <USER_A_TOKEN>

file: <zip with PUDDLEJUMP.md and Documents/ but no puddlejump.json>
```

**Expected**
- 400 Bad Request
- Error references missing manifest

---

### B5) Sync upload — path traversal attempt

**Request**
```
POST /api/stackroom/puddlejump/sync/upload
Authorization: Bearer <USER_A_TOKEN>
Content-Type: multipart/form-data

file: <any .md file>
path: ../../etc/passwd.md
```

**Expected**
- 400 Bad Request
- `{"error": "Invalid file path"}`

**Verify**
- [ ] `../` in path is rejected
- [ ] No file is written to storage

---

### B6) Sync upload — absolute path attempt

**Request**
```
POST /api/stackroom/puddlejump/sync/upload
Authorization: Bearer <USER_A_TOKEN>
Content-Type: multipart/form-data

file: <any .md file>
path: /etc/notes.md
```

**Expected**
- 400 Bad Request
- `{"error": "Invalid file path"}`

---

### B7) Sync upload — file exceeds 5MB

**Request**
```
POST /api/stackroom/puddlejump/sync/upload
Authorization: Bearer <USER_A_TOKEN>
Content-Type: multipart/form-data

file: <markdown file > 5MB>
path: large-doc.md
```

**Expected**
- 400 Bad Request
- `{"error": "File exceeds maximum size of 5MB"}`

---

### B8) Sync upload — non-markdown file extension

**Request**
```
POST /api/stackroom/puddlejump/sync/upload
Authorization: Bearer <USER_A_TOKEN>
Content-Type: multipart/form-data

file: <any file>
path: notes.txt
```

**Expected**
- 400 Bad Request
- `{"error": "Only markdown files (.md) are allowed"}`

---

## Section C — Canon Approval Permission (D4)

### C1) Approve — by library owner (should succeed)

**Precondition:** Submit a version first via `POST .../versions` as `user_a`. Note the `id` as `<VERSION_ID>`.

**Request**
```
POST /api/stackroom/source-files/<SOURCE_FILE_ID>/approve
Authorization: Bearer <USER_A_TOKEN>
Content-Type: application/json

{"version_id": "<VERSION_ID>"}
```

**Expected**
- 200 OK
- `{"is_canon": true, "approved_at": "...", ...}`

---

### C2) Approve — by non-member (should fail)

**Request**
```
POST /api/stackroom/source-files/<SOURCE_FILE_ID>/approve
Authorization: Bearer <USER_B_TOKEN>
Content-Type: application/json

{"version_id": "<VERSION_ID>"}
```

**Expected**
- 404 Not Found (access check runs before permission check)

---

### C3) Approve — group library, by member not admin (should fail)

**Precondition:** Group library with `user_member` as a basic member (role: `['member']`), not admin. SourceFile in that library. Version submitted.

**Request**
```
POST /api/stackroom/source-files/<GROUP_SOURCE_FILE_ID>/approve
Authorization: Bearer <USER_MEMBER_TOKEN>
Content-Type: application/json

{"version_id": "<GROUP_VERSION_ID>"}
```

**Expected**
- 403 Forbidden
- `{"error": "You do not have permission to approve Canon for this library."}`

**Verify**
- [ ] Member can access the file (A-series checks pass) but cannot approve canon

---

### C4) Approve — group library, by group admin (should succeed)

**Precondition:** `user_a` is admin of the group that sponsors the library.

**Request**
```
POST /api/stackroom/source-files/<GROUP_SOURCE_FILE_ID>/approve
Authorization: Bearer <USER_A_TOKEN>
Content-Type: application/json

{"version_id": "<GROUP_VERSION_ID>"}
```

**Expected**
- 200 OK
- `{"is_canon": true, ...}`

---

## Section D — Library Status Endpoint (D5)

### D1) Status — own library

**Request**
```
GET /api/stackroom/libraries/<PERSONAL_LIB_ID>/status
Authorization: Bearer <USER_A_TOKEN>
```

**Expected**
- 200 OK
- Response contains:
  - `library_id` — matches `<PERSONAL_LIB_ID>`
  - `bundle_id` — string or null
  - `file_count` — integer ≥ 0
  - `canonical_count` — integer ≤ file_count
  - `ingestion_status` — object with `ready`, `processing`, `failed`, `pending` (all integers)
  - `last_sync` — ISO 8601 string or null
  - `warnings` — array (may be empty)

**Verify**
- [ ] `file_count` matches count of SourceFiles in this library
- [ ] `canonical_count` matches count of SourceFiles where `is_canon=True`
- [ ] If no canonical files, `warnings` contains `{"code": "WARN_NO_CANONICAL", ...}`
- [ ] `ingestion_status` keys sum to `file_count`

---

### D2) Status — library with >250 files

**Precondition:** Library with 260 files.

**Request**
```
GET /api/stackroom/libraries/<LARGE_LIB_ID>/status
Authorization: Bearer <USER_A_TOKEN>
```

**Expected**
- `warnings` contains `{"code": "WARN_APPROACHING_LIMIT", "file_count": 260, ...}`

---

## Section E — Group Library Access for Utility Views (S5)

### E1) Utility health — group library, by active member

**Precondition:** Group library with `user_member` as active member. Library has been ingested.

**Request**
```
GET /api/stackroom/puddlejump/utilities/libraries/<GROUP_LIB_ID>/health
Authorization: Bearer <USER_MEMBER_TOKEN>
```

**Expected**
- 200 OK (previously this returned 404 — this is the regression being fixed)

---

### E2) Utility health — group library, by non-member

**Request**
```
GET /api/stackroom/puddlejump/utilities/libraries/<GROUP_LIB_ID>/health
Authorization: Bearer <USER_B_TOKEN>
```

**Expected**
- 404 Not Found
- `{"error": "Library not found or access denied"}`

---

## Section F — `top_n` Bound Check (S6)

### F1) Canonical candidates — top_n over limit

**Request**
```
POST /api/stackroom/puddlejump/utilities/suggest-canonical
Authorization: Bearer <USER_A_TOKEN>
Content-Type: application/json

{"library_id": "<PERSONAL_LIB_ID>", "top_n": 500}
```

**Expected**
- 400 Bad Request
- `{"error": "top_n must be an integer between 1 and 100"}`

---

### F2) Canonical candidates — top_n at limit

**Request**
```
POST /api/stackroom/puddlejump/utilities/suggest-canonical
Authorization: Bearer <USER_A_TOKEN>
Content-Type: application/json

{"library_id": "<PERSONAL_LIB_ID>", "top_n": 100}
```

**Expected**
- 200 OK
- `candidate_count` ≤ 100

---

## Regression Checks

- `GET /api/stackroom/puddlejump/personal` still returns personal library for `user_a`
- `POST /api/stackroom/puddlejump/import` still processes a valid bundle end-to-end
- Sync status/upload/download/delete/complete still work for authenticated user
- Existing utility endpoints still work for personal library owner
- `GET /api/stackroom/puddlejump/health` still returns 200 without auth

---

## Notes / Known Constraints

- **S8 (deferred):** Canon approval still triggers `process_pending_uploads` (batch task) rather than a targeted per-file task. This is a known limitation, not a test failure.
- Group library tests require seeded group + membership data — coordinate with test data setup.
- The zip bomb test (B-series) uses actual uncompressed byte measurement; a zip with honest headers and honest content of 50.1MB should be rejected. Testing a zip-bomb specifically requires a crafted malicious file — flag this for the security testing team separately.
