# Stackroom Embedding & Retrieval - Testing Guide

## Overview

This guide shows how to test and demonstrate the complete Stackroom embedding and retrieval system to stakeholders.

## Prerequisites

1. **Qdrant Running**: Ensure Qdrant is running on `localhost:6333`
   ```bash
   # Check if Qdrant is running
   curl http://localhost:6333/

   # If not running, start it (adjust path as needed)
   docker run -p 6333:6333 qdrant/qdrant
   ```

2. **Environment Setup**:
   ```bash
   cd REDACTED-LOCAL-PATH/mixtape-release-core/app
   source ../env/bin/activate
   ```

3. **Optional: OpenAI API Key** (for OpenAI embeddings)
   ```bash
   export OPENAI_API_KEY="your-api-key-here"
   ```
   Note: Tests use sentence-transformers (local) by default, no API key needed

---

## Quick Test Suite (Recommended for Stakeholders)

### 1. Run All Stackroom Tests (2-3 minutes)

```bash
DJANGO_SETTINGS_MODULE=mixtape.settings.dev ./env/bin/python manage.py test stackroom --keepdb
```

**Expected Output:**
- ✅ **78+ tests passing**
- Includes: unit tests, integration tests, retrieval API tests
- Shows real Qdrant collections being created
- Demonstrates sentence-transformers embeddings

**Key Test Categories:**
- **Embedding Contract Tests** (7 tests) - Verify authority boundaries
- **Qdrant Naming Tests** (14 tests) - Collection naming conventions
- **Qdrant Client Tests** (14 tests) - Vector database operations
- **Embedding Provider Tests** (13 tests) - OpenAI & sentence-transformers
- **Embedding Service Tests** (15 tests) - Backfill, stale detection
- **Celery Task Tests** (7 tests) - Async embedding generation
- **Retrieval API Tests** (8 tests) - Semantic search endpoint
- **Integration Tests** (5 tests) - End-to-end workflows

---

## Integration Tests (Shows Real Workflows)

### Run Just Integration Tests

```bash
DJANGO_SETTINGS_MODULE=mixtape.settings.dev ./env/bin/python manage.py test stackroom.tests.test_integration_embedding_retrieval --verbosity=2 --keepdb
```

**Duration:** ~15 seconds

**What Gets Tested:**

#### Test 1: End-to-End Pipeline
✅ **Workflow:**
1. Create library with realistic chunks about Python, JavaScript, Machine Learning
2. Backfill chunk embeddings (3 chunks)
3. Generate real sentence-transformer embeddings (384 dimensions)
4. Upsert to Qdrant
5. Query via semantic retrieval API
6. Verify Python chunk returned for "Python programming" query

**Demonstrates:** Full ingestion → embedding → retrieval cycle

#### Test 2: Library Isolation
✅ **Workflow:**
1. Create two separate libraries
2. Embed both libraries
3. Verify separate Qdrant collections
4. Verify no cross-library data leakage

**Demonstrates:** Multi-tenancy security

#### Test 3: Stale Embedding Detection
✅ **Workflow:**
1. Create embeddings for chunks
2. Modify chunk text (simulating content update)
3. Verify stale detection (hash mismatch)
4. Mark stale embeddings as pending for re-embedding

**Demonstrates:** Content drift detection

#### Test 4: Idempotent Backfill
✅ **Workflow:**
1. Run backfill (creates 3 embeddings)
2. Run backfill again
3. Verify no duplicates created (0 new, 3 existing)

**Demonstrates:** Retry safety

#### Test 5: Multiple Embedding Models
✅ **Workflow:**
1. Backfill same library with two different models
2. Verify both model embeddings exist (3 chunks × 2 models = 6 total)

**Demonstrates:** Multi-model support

---

## Management Command Demo (Interactive)

### Show Embedding Statistics

```bash
DJANGO_SETTINGS_MODULE=mixtape.settings.dev ./env/bin/python manage.py embed_chunks --stats
```

**Output:**
```
📊 Embedding Statistics

Total:    150
Pending:  12
Complete: 135
Failed:   3
```

### Embed a Library (Async via Celery)

```bash
# Get a library ID first
LIBRARY_ID="<your-library-uuid>"

# Trigger async embedding
DJANGO_SETTINGS_MODULE=mixtape.settings.dev ./env/bin/python manage.py embed_chunks \
  --library $LIBRARY_ID \
  --model all-MiniLM-L6-v2 \
  --model-version 1 \
  --provider sentence-transformers
```

**Output:**
```
Library: My Test Library
Model: all-MiniLM-L6-v2@1
Provider: sentence-transformers

🚀 Starting async embedding...
✅ Task enqueued: abc-123-def-456
Monitor progress with: celery -A mixtape inspect active
```

### Embed Synchronously (For Testing)

```bash
DJANGO_SETTINGS_MODULE=mixtape.settings.dev ./env/bin/python manage.py embed_chunks \
  --library $LIBRARY_ID \
  --model all-MiniLM-L6-v2 \
  --model-version 1 \
  --provider sentence-transformers \
  --sync \
  --limit 10
```

**Output:**
```
⚠️  Running in SYNC mode...
✅ Created EmbeddingModel: all-MiniLM-L6-v2@1
📊 Backfilling ChunkEmbedding rows...
   Created: 10, Existing: 0
   Collection: stackroom__lib_<uuid>__emb__all-MiniLM-L6-v2__1

🔄 Processing 10 chunks synchronously...
  [1/10] ✓ chunk-uuid-1
  [2/10] ✓ chunk-uuid-2
  ...
  [10/10] ✓ chunk-uuid-10

✅ Complete: 10 success, 0 errors
```

### Detect Stale Embeddings

```bash
# Show stale count
DJANGO_SETTINGS_MODULE=mixtape.settings.dev ./env/bin/python manage.py embed_chunks \
  --library $LIBRARY_ID \
  --stats

# Mark stale as pending for re-embedding
DJANGO_SETTINGS_MODULE=mixtape.settings.dev ./env/bin/python manage.py embed_chunks \
  --library $LIBRARY_ID \
  --mark-stale
```

**Output:**
```
🔍 Checking for stale embeddings...
✅ Marked 5 stale embeddings as PENDING
```

---

## API Testing (Using curl or httpie)

### Prerequisites: Get Service JWT Token

```bash
# Create service token (adjust script path)
SERVICE_TOKEN=$(python scripts/generate_service_jwt.py stackroom:ir)
```

### Test Retrieval API

```bash
curl -X POST http://localhost:8000/api/stackroom/retrieve \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $SERVICE_TOKEN" \
  -d '{
    "query": "python programming language",
    "library_id": "'$LIBRARY_ID'",
    "model_name": "all-MiniLM-L6-v2",
    "model_version": "1",
    "limit": 5
  }'
```

**Expected Response:**
```json
{
  "query": "python programming language",
  "results": [
    {
      "chunk_id": "chunk-uuid-1",
      "text": "Python is a high-level programming language...",
      "score": 0.87,
      "source_spans": [{"char_start": 0, "char_end": 85}],
      "artifact_id": "artifact-uuid",
      "artifact_type": "extracted_text",
      "source_file_id": "file-uuid",
      "filename": "document.txt",
      "path": "docs/document.txt"
    }
  ],
  "model": "all-MiniLM-L6-v2@1",
  "collection": "stackroom__lib_<uuid>__emb__all-MiniLM-L6-v2__1"
}
```

### Test with Score Threshold

```bash
curl -X POST http://localhost:8000/api/stackroom/retrieve \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $SERVICE_TOKEN" \
  -d '{
    "query": "machine learning",
    "library_id": "'$LIBRARY_ID'",
    "model_name": "all-MiniLM-L6-v2",
    "model_version": "1",
    "limit": 10,
    "score_threshold": 0.75
  }'
```

---

## Qdrant Inspection (Verify Collections)

### List All Collections

```bash
curl http://localhost:6333/collections
```

**Expected:**
```json
{
  "result": {
    "collections": [
      {
        "name": "stackroom__lib_abc123__emb__all-MiniLM-L6-v2__1"
      },
      {
        "name": "stackroom__lib_def456__emb__text-embedding-3-small__1"
      }
    ]
  }
}
```

### Inspect Collection Details

```bash
COLLECTION="stackroom__lib_abc123__emb__all-MiniLM-L6-v2__1"
curl "http://localhost:6333/collections/$COLLECTION"
```

**Shows:**
- Vector dimensions
- Number of points (embeddings)
- Distance metric (Cosine)

### Count Points in Collection

```bash
curl "http://localhost:6333/collections/$COLLECTION/points/count"
```

---

## Stakeholder Demo Script

### 1. Show Test Coverage (1 minute)

```bash
# Run all tests
DJANGO_SETTINGS_MODULE=mixtape.settings.dev ./env/bin/python manage.py test stackroom --keepdb

# Point out: 78+ passing tests, real Qdrant integration
```

**Key Message:** "Comprehensive test coverage ensures reliability"

### 2. Show End-to-End Integration (2 minutes)

```bash
# Run integration tests with verbose output
DJANGO_SETTINGS_MODULE=mixtape.settings.dev ./env/bin/python manage.py test \
  stackroom.tests.test_integration_embedding_retrieval \
  --verbosity=2 --keepdb
```

**Key Message:** "Real embeddings, real vector database, real retrieval"

### 3. Show Management Commands (2 minutes)

```bash
# Show stats
DJANGO_SETTINGS_MODULE=mixtape.settings.dev ./env/bin/python manage.py embed_chunks --stats

# Show help
DJANGO_SETTINGS_MODULE=mixtape.settings.dev ./env/bin/python manage.py embed_chunks --help
```

**Key Message:** "Operators have tools to manage embeddings"

### 4. Show Qdrant Collections (1 minute)

```bash
# Show collections
curl http://localhost:6333/collections | python -m json.tool
```

**Key Message:** "Vector database is properly isolated by library and model"

### 5. Show Contract Enforcement (1 minute)

```bash
# Run contract tests specifically
DJANGO_SETTINGS_MODULE=mixtape.settings.dev ./env/bin/python manage.py test \
  stackroom.tests.test_embedding_contract --verbosity=2 --keepdb
```

**Key Message:** "Django is authority, Qdrant is derived index - contract enforced"

---

## Troubleshooting

### Qdrant Connection Errors

```bash
# Verify Qdrant is running
curl http://localhost:6333/
```

**Fix:** Start Qdrant container:
```bash
docker run -p 6333:6333 qdrant/qdrant
```

### Test Database Exists

**Error:** `database "test_crossroads_stage" already exists`

**Fix:** Use `--keepdb` flag or destroy and recreate:
```bash
DJANGO_SETTINGS_MODULE=mixtape.settings.dev ./env/bin/python manage.py test stackroom --keepdb
```

### Sentence-Transformers Model Download

**First Run:** Downloads `all-MiniLM-L6-v2` model (~100MB)

**Location:** `~/.cache/torch/sentence_transformers/`

---

## Performance Notes

### Integration Test Performance
- **Duration:** ~15 seconds for 5 tests
- **Bottleneck:** Sentence-transformer model loading (first time)
- **Subsequent Runs:** ~8 seconds (cached model)

### Embedding Performance (Local)
- **sentence-transformers:** ~100-200 chunks/second
- **OpenAI API:** ~50-100 chunks/second (rate limits)

### Retrieval Performance
- **Qdrant Search:** <10ms for collections <100k points
- **Django Hydration:** ~5-10ms for 10 chunks
- **Total Latency:** ~50-100ms end-to-end

---

## Success Criteria Checklist

- [x] ✅ All unit tests passing (70+ tests)
- [x] ✅ Integration tests demonstrate end-to-end flow
- [x] ✅ Library isolation enforced in tests
- [x] ✅ Stale embedding detection works
- [x] ✅ Idempotent backfills verified
- [x] ✅ Multiple embedding models supported
- [x] ✅ Management commands functional
- [x] ✅ Retrieval API returns accurate results
- [x] ✅ Qdrant collections properly namespaced
- [x] ✅ Contract rules enforced (Django = authority)

---

## Next Steps

1. **Production Setup:**
   - Configure Qdrant cluster
   - Set up Celery workers for async embedding
   - Configure OpenAI API key

2. **Monitoring:**
   - Track embedding success/failure rates
   - Monitor Qdrant collection sizes
   - Alert on stale embeddings > threshold

3. **Optimization:**
   - Batch embedding for large libraries
   - Implement embedding caching
   - Add retrieval result caching

---

## Contact

For questions or issues, refer to:
- Contract Documentation: `/stackroom/docs/EMBEDDING_CONTRACT.md`
- Architecture Overview: `/stackroom/docs/ARCHITECTURE.md`
- API Reference: `/stackroom/docs/API.md`
