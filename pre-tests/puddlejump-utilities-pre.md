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

## Phase 6-7: LLM Utilities (Inkwell)

These endpoints depend on Inkwell (the FastAPI LLM microservice). Verify it's running first:
```
curl $INKWELL_BASE_URL/health/ready
```
Expected: `{"status": "ready", ...}` with HTTP 200. If Inkwell is down, suggest-summaries returns per-artifact errors and restructure returns an empty cluster list — both degrade gracefully.

---

## 13) Suggest Summaries

**Request**
```
POST /api/stackroom/puddlejump/utilities/suggest-summaries
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
  - `total_missing` — integer ≥ 0 (artifacts without interior_summary)
  - `suggestions_generated` — integer ≤ total_missing
  - `suggestions` — array of objects, each with:
    - `artifact_id` — valid UUID
    - `source_file_id` — valid UUID
    - `filename` — actual filename
    - `suggested_summary` — non-empty string (when successful)
    - `method` — e.g. "llm_abstractive", "extractive_fallback", "skipped_too_short", "error"
    - `error` — null on success, error message string on failure

**Verify**
- [ ] If all artifacts already have summaries, `total_missing` is 0 and `suggestions` is empty
- [ ] Artifacts with < 50 chars text get `method: "skipped_too_short"`
- [ ] Summaries read as coherent natural language
- [ ] If Inkwell is down, each suggestion has `method: "error"` and a descriptive `error` string
- [ ] Does NOT write summaries back to artifacts — read-only

---

## 14) Restructure / Consolidate

**Request**
```
POST /api/stackroom/puddlejump/utilities/restructure
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
  - `similarity_threshold` — 0.6 (default)
  - `cluster_count` — integer ≥ 0
  - `clusters` — array of objects, each with:
    - `cluster_id` — integer starting from 0
    - `documents` — array of `{source_file_id, filename, excerpt}`
    - `document_count` — integer ≥ 2 (clusters always have 2+ docs)
    - `similarity_avg` — float 0.0-1.0 (average pairwise similarity within cluster)
    - `outline` — summary text from Inkwell (or empty if Inkwell down)
    - `outline_method` — "llm_abstractive", "extractive_fallback", "error", or "none"
  - Sorted by `document_count` descending

**Verify**
- [ ] Each cluster has at least 2 documents
- [ ] Documents within a cluster are genuinely related (check filenames/excerpts)
- [ ] Outlines make sense as consolidation summaries
- [ ] No document appears in more than one cluster
- [ ] If Inkwell is down, clusters still form (embedding-based) but outlines are empty with `outline_method: "error"`

---

## 15) Restructure — Custom Threshold

**Request**
```
POST /api/stackroom/puddlejump/utilities/restructure
Authorization: Bearer <TOKEN>
Content-Type: application/json

{
    "library_id": "<LIBRARY_ID>",
    "similarity_threshold": 0.8
}
```

**Expected**
- 200 OK
- Higher threshold → fewer, tighter clusters (or none)
- All documents in each cluster have pairwise similarity ≥ 0.8

---

## Frontend UI Testing

### Prerequisites
- Django dev server running (port 8011 or similar)
- Inkwell running (check `/health/ready`)
- Qdrant running (port 6333)
- Frontend running (`yarn dev` on port 3010)
- Logged in as a user with a Puddlejump library containing synced, ingested files

### Navigate to Puddlejump
1. Go to `/puddlejump` in the browser
2. Sidebar should show two sections: **Library** (Overview, Files) and **Utilities** (Duplicates, Glossary, Canonical, Summaries, Restructure)

### Test each panel

**Overview** (default view)
- [ ] Loads automatically — shows file count, total size, folder depth
- [ ] Coverage bars (canon, summary, keyword) show correct percentages
- [ ] Ingestion status bar reflects embedding completion
- [ ] Missing summaries alert expands to show filenames (if any exist)
- [ ] Overdue reviews alert shows (if any canonical items have past review dates)

**Files**
- [ ] Files grouped by folder path, root files listed first
- [ ] Folder sections are collapsible
- [ ] Clicking a file expands detail: path, canonical status, tags, updated date
- [ ] File sizes display correctly (bytes/KB/MB)
- [ ] "canon" badge appears on featured files

**Duplicates**
- [ ] Default threshold shows 0.85 in input
- [ ] Click "Run Analysis" — spinner appears, then results
- [ ] Pairs show filenames, similarity percentage, text excerpts
- [ ] High similarity (≥ 95%) gets red badge, lower gets yellow
- [ ] Zero-pair result shows green "No duplicates found" message
- [ ] Changing threshold and re-running updates results

**Glossary**
- [ ] Click "Extract Glossary" — spinner, then results
- [ ] Terms show with definitions (if pattern-matched), occurrence counts, source file badges
- [ ] Sort toggle switches between frequency and A-Z ordering
- [ ] Min occurrences filter reduces results when increased

**Canonical**
- [ ] Click "Find Candidates" — spinner, then ranked results
- [ ] Candidates show rank number, filename, score bar, reason list
- [ ] "canonical" badge appears on already-canonical files
- [ ] "Exclude already canonical" checkbox filters them out on re-run
- [ ] Top N input limits the result count

**Summaries** (Phase 6 — requires Inkwell)
- [ ] Click "Suggest Summaries" — spinner appears (may take 10-30s depending on file count)
- [ ] Results show filename, method badge, and suggested summary in a blue-bordered card
- [ ] Dismiss button (X) removes a suggestion from the list
- [ ] Count badges update: "N generated" and "N total missing"
- [ ] If all files already have summaries, shows "All documents already have summaries"
- [ ] Skipped/error counts appear at bottom when relevant
- [ ] If Inkwell is down: error messages appear per-artifact, not a full page crash

**Restructure** (Phase 7 — requires Inkwell + Qdrant embeddings)
- [ ] Default threshold shows 0.6 in input
- [ ] Click "Analyze Structure" — spinner (may take 10-30s)
- [ ] Clusters appear as cards with: cluster number, document count, avg similarity badge
- [ ] Each cluster lists its member documents with filenames and excerpts
- [ ] Purple-bordered "Suggested outline" section appears below each cluster's documents
- [ ] Zero-cluster result shows green "No document clusters found" message
- [ ] Raising threshold (e.g. 0.8) produces fewer, tighter clusters

### Error states to verify
- [ ] If Inkwell is down: Summaries and Restructure degrade gracefully (no crash, clear error messaging)
- [ ] If Qdrant has no embeddings: Duplicates, Canonical, and Restructure return empty results (not errors)
- [ ] If library has no files: Overview shows zero counts, Files shows empty state, utilities return empty

---

## Notes / Known Constraints
- Duplicate detection and canonical candidates return empty results if ingestion hasn't completed (no embeddings in Qdrant). This is expected — not a failure.
- Glossary extraction works purely from artifact text and keywords, so it returns results even without embeddings.
- Summaries and Restructure depend on Inkwell. Both degrade gracefully if it's unavailable.
- `llm_provider.py` has been deleted — all LLM operations go through `inkwell/client.py` → Inkwell FastAPI.
- All utility operations are synchronous. For large libraries (200+ files), LLM-based operations (summaries, restructure) may take 30-60s due to per-document Inkwell calls.
- Suggest Summaries does NOT write back to artifacts — it's a proposal for user review only.
