# Puddlejump Utilities — Pre‑Test Handoff

**Scope**
Validate the four new Puddlejump utility endpoints: library health, duplicate detection, glossary extraction, and canonical candidate suggestion. All endpoints live under `/api/stackroom/puddlejump/utilities/`.

**Key Principles**
- All endpoints require authentication (OAuth2, JWT, or session).
- User must be the sponsor (owner) of the library to access its utilities.
- Health is a GET; the other three are POST with `library_id` in the request body.
- No write operations — these are read-only analysis tools.
- Duplicate detection and canonical suggestions depend on Qdrant embeddings being present (ingestion must have completed for the library).

---

## Preconditions
- Local dev env up with Qdrant running (`localhost:6333`).
- Test user exists with a personal Puddlejump library containing synced files.
- Files have been ingested (Celery tasks completed: SourceFile → Artifact → Shard → Chunk → ChunkEmbedding).
- Get the user's personal puddlejump library ID:
  ```
  GET /api/stackroom/puddlejump/personal
  ```
  Note the `id` field in the response — this is `<LIBRARY_ID>` for all tests below.
- Get a valid auth token (session cookie, JWT, or OAuth2 Bearer token).

---

## 1) Library Health

**Request**
```
GET /api/stackroom/puddlejump/utilities/libraries/<LIBRARY_ID>/health
Authorization: Bearer <TOKEN>
```

**Expected**
- 200 OK
- Response contains:
  - `library_id` — matches the requested ID
  - `file_count` — integer, matches number of non-folder items in the library
  - `total_size_bytes` — integer ≥ 0
  - `folder_depth` — integer 0-3
  - `canon_coverage.total_items` — total non-folder LibraryItems
  - `canon_coverage.canonical_items` — count where `is_featured=True`
  - `canon_coverage.percentage` — correct ratio
  - `summary_coverage.total_artifacts` — total artifacts for this library
  - `summary_coverage.with_summary` — count where `interior_summary` is non-empty
  - `keyword_coverage.with_keywords` — count where `keywords` is non-empty
  - `missing_summaries` — array of `{filename, source_file_id, artifact_id}`
  - `overdue_reviews` — array (may be empty if no canonical items have review dates)
  - `ingestion_status.fully_embedded` — count of completed ChunkEmbeddings
  - `ingestion_status.percentage_complete` — number 0-100

**Verify**
- [ ] `file_count` matches `GET /puddlejump/personal` → count of non-folder items
- [ ] `summary_coverage.total_artifacts` matches the number of artifacts you expect
- [ ] If no files are marked canonical, `canon_coverage.canonical_items` is 0
- [ ] `ingestion_status.percentage_complete` reflects actual embedding state

---

## 2) Library Health — Access Denied

**Request**
```
GET /api/stackroom/puddlejump/utilities/libraries/<OTHER_USERS_LIBRARY_ID>/health
Authorization: Bearer <TOKEN>
```

**Expected**
- 404 Not Found
- `{"error": "Library not found or access denied"}`

**Verify**
- [ ] Cannot access another user's library health
- [ ] No information leak (404 not 403)

---

## 3) Duplicate Detection

**Request**
```
POST /api/stackroom/puddlejump/utilities/check-duplicates
Authorization: Bearer <TOKEN>
Content-Type: application/json

{
    "library_id": "<LIBRARY_ID>"
}
```

**Expected**
- 200 OK
- Response contains:
  - `library_id` — matches
  - `similarity_threshold` — 0.85 (default)
  - `pair_count` — integer ≥ 0
  - `pairs` — array of objects, each with:
    - `source_file_a_id`, `filename_a`
    - `source_file_b_id`, `filename_b`
    - `similarity_score` — float between threshold and 1.0
    - `excerpt_a`, `excerpt_b` — text snippets (up to 200 chars)
  - Pairs sorted by `similarity_score` descending

**Verify**
- [ ] If library has files with similar content, pairs are returned
- [ ] All `similarity_score` values are ≥ 0.85
- [ ] Filenames correspond to actual files in the library
- [ ] No self-pairs (file compared to itself)

---

## 4) Duplicate Detection — Custom Threshold

**Request**
```
POST /api/stackroom/puddlejump/utilities/check-duplicates
Authorization: Bearer <TOKEN>
Content-Type: application/json

{
    "library_id": "<LIBRARY_ID>",
    "similarity_threshold": 0.70
}
```

**Expected**
- 200 OK
- `similarity_threshold` is 0.70 in response
- More pairs returned than with 0.85 threshold (or equal)
- All scores ≥ 0.70

**Verify**
- [ ] Lower threshold returns equal or more pairs
- [ ] Threshold is reflected in response

---

## 5) Duplicate Detection — Invalid Threshold

**Request**
```
POST /api/stackroom/puddlejump/utilities/check-duplicates
Authorization: Bearer <TOKEN>
Content-Type: application/json

{
    "library_id": "<LIBRARY_ID>",
    "similarity_threshold": 1.5
}
```

**Expected**
- 400 Bad Request
- `{"error": "similarity_threshold must be a number between 0 and 1"}`

---

## 6) Glossary Extraction

**Request**
```
POST /api/stackroom/puddlejump/utilities/extract-glossary
Authorization: Bearer <TOKEN>
Content-Type: application/json

{
    "library_id": "<LIBRARY_ID>"
}
```

**Expected**
- 200 OK
- Response contains:
  - `library_id` — matches
  - `min_occurrences` — 1 (default)
  - `term_count` — integer ≥ 0
  - `terms` — array of objects, each with:
    - `term` — the extracted term string
    - `definition` — definition text (may be empty for keyword-only terms)
    - `source_files` — array of `{filename, source_file_id, artifact_id}`
    - `occurrences` — integer ≥ 1
  - Sorted by occurrences descending, then alphabetically

**Verify**
- [ ] Terms with bold definitions (`**Term**: definition`) are captured with definitions
- [ ] TF-IDF keywords appear as terms (possibly without definitions)
- [ ] `source_files` references are valid
- [ ] If a term appears in multiple files, `source_files` lists each one

---

## 7) Glossary Extraction — Min Occurrences Filter

**Request**
```
POST /api/stackroom/puddlejump/utilities/extract-glossary
Authorization: Bearer <TOKEN>
Content-Type: application/json

{
    "library_id": "<LIBRARY_ID>",
    "min_occurrences": 3
}
```

**Expected**
- 200 OK
- All returned terms have `occurrences` ≥ 3
- Fewer terms than with `min_occurrences: 1`

---

## 8) Canonical Candidates

**Request**
```
POST /api/stackroom/puddlejump/utilities/suggest-canonical
Authorization: Bearer <TOKEN>
Content-Type: application/json

{
    "library_id": "<LIBRARY_ID>"
}
```

**Expected**
- 200 OK
- Response contains:
  - `library_id` — matches
  - `top_n` — 10 (default)
  - `candidate_count` — integer ≥ 0, ≤ 10
  - `candidates` — array of objects, each with:
    - `source_file_id` — valid UUID
    - `filename` — actual filename
    - `score` — float 0.0-1.0
    - `reasons` — array of human-readable strings explaining the score
    - `is_canonical` — boolean (current status)
    - `library_item_id` — UUID or empty string
  - Sorted by `score` descending

**Verify**
- [ ] Longer, well-structured files score higher than short stubs
- [ ] Files referenced by other files get a reason mentioning "Referenced by"
- [ ] `is_canonical` correctly reflects `LibraryItem.is_featured` status
- [ ] Reasons are readable and make sense

---

## 9) Canonical Candidates — Exclude Already Canonical

**Request**
```
POST /api/stackroom/puddlejump/utilities/suggest-canonical
Authorization: Bearer <TOKEN>
Content-Type: application/json

{
    "library_id": "<LIBRARY_ID>",
    "exclude_already_canonical": true
}
```

**Expected**
- 200 OK
- No candidate has `is_canonical: true`

---

## 10) Canonical Candidates — Custom top_n

**Request**
```
POST /api/stackroom/puddlejump/utilities/suggest-canonical
Authorization: Bearer <TOKEN>
Content-Type: application/json

{
    "library_id": "<LIBRARY_ID>",
    "top_n": 3
}
```

**Expected**
- 200 OK
- `candidate_count` ≤ 3

---

## 11) Missing library_id

**Request** (applies to all three POST endpoints)
```
POST /api/stackroom/puddlejump/utilities/check-duplicates
Authorization: Bearer <TOKEN>
Content-Type: application/json

{}
```

**Expected**
- 400 Bad Request
- `{"error": "library_id is required"}`

---

## 12) Unauthenticated Access

**Request** (applies to all endpoints)
```
GET /api/stackroom/puddlejump/utilities/libraries/<LIBRARY_ID>/health
(no Authorization header)
```

**Expected**
- 401 Unauthorized or 403 Forbidden

---

## Regression Checks
- Existing Puddlejump endpoints still work: `GET /puddlejump/personal`, `POST /puddlejump/import`, sync endpoints.
- Library placements and activity endpoints unaffected.
- Qdrant operations in utilities are read-only — no points upserted or deleted.

---

## Notes / Known Constraints
- Duplicate detection and canonical candidates return empty results if ingestion hasn't completed (no embeddings in Qdrant). This is expected — not a failure.
- Glossary extraction works purely from artifact text and keywords, so it returns results even without embeddings.
- The LLM provider (`llm_provider.py`) is a skeleton — no endpoints depend on it yet. It will be used by future utilities (suggest summaries, restructure).
- All utility operations are synchronous. For large libraries (200+ files), duplicate detection may take a few seconds due to Qdrant round-trips.
