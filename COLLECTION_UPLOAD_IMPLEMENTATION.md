# Collection Upload Implementation

## Summary

Implemented deferred ingestion for Collection file uploads, separating the curation workflow (Collections) from the IR/search workflow (Stackroom).

## Architecture

### Mental Model Separation

**Collections (Curation Layer)**
- Focus: Organizing, presenting, curating whole files
- Upload creates file metadata only
- Indexing happens in background, user doesn't think about it
- Search: Simple keyword/phrase search (future)

**Stackroom (IR/Retrieval Layer)**
- Focus: Parsing, chunking, embedding, semantic search
- Upload triggers immediate processing
- User cares about when indexing completes
- Search: Semantic + keyword search

## Implementation Details

### 1. Collection Upload Endpoint

**Endpoint:** `POST /api/collections/{collection_id}/upload`

**What it does:**
- Accepts file upload
- Computes SHA-256 hash for deduplication
- Saves file to Django storage (`stackroom_uploads/{library_id}/{hash}_{filename}`)
- Creates SourceFile record with file metadata
- Does NOT create IngestionRun (deferred)
- Returns immediately with source_file_id

**Files changed:**
- `stackroom/api/collection_serializers.py` - Added upload serializers
- `stackroom/api/collection_views.py` - Added CollectionFileUploadView
- `stackroom/api/collection_urls.py` - Added upload URL pattern

### 2. Periodic Ingestion Task

**Task:** `stackroom.tasks.processing.process_pending_uploads`

**What it does:**
- Runs every 15 seconds via Celery Beat
- Finds SourceFiles without IngestionRuns (up to 10 per run)
- For each file:
  - Reads file content from storage
  - Extracts text (supports .txt, .md, .pdf, .docx, etc.)
  - Creates IngestionRun (status: running)
  - Creates Artifact with extracted text
  - Creates IngestionReceipt
  - Queues process_artifact task (chunking + embedding)

**Files changed:**
- `stackroom/tasks/processing.py` - Added process_pending_uploads task and _extract_text_from_bytes helper
- `mixtape/celery_app.py` - Configured beat_schedule to run every 15 seconds

## Testing

### Manual Test Flow

1. **Start services:**
   ```bash
   # Terminal 1: Django server
   cd app
   python manage.py runserver 8010

   # Terminal 2: Celery worker
   cd app
   celery -A mixtape worker -l info

   # Terminal 3: Celery beat (for periodic tasks)
   cd app
   celery -A mixtape beat -l info
   ```

2. **Upload a file via Collection endpoint:**
   ```bash
   # Create a test file
   echo "This is a test file for Collection upload" > test.txt

   # Get a collection ID (or create one via API/admin)
   COLLECTION_ID="your-collection-uuid-here"

   # Upload file
   curl -X POST \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -F "file=@test.txt" \
     http://localhost:8010/api/collections/$COLLECTION_ID/upload/
   ```

3. **Verify SourceFile created without IngestionRun:**
   ```bash
   # Django shell
   python manage.py shell

   >>> from stackroom.models import SourceFile, IngestionRun
   >>> sf = SourceFile.objects.latest('created_at')
   >>> sf.filename
   'test.txt'
   >>> sf.ingestion_runs.count()
   0  # Should be 0 initially
   ```

4. **Wait 15 seconds** (or manually trigger task):
   ```python
   # In Django shell
   >>> from stackroom.tasks.processing import process_pending_uploads
   >>> result = process_pending_uploads()
   >>> result
   {'processed_count': 1, 'failed_count': 0, 'skipped_count': 0}
   ```

5. **Verify ingestion completed:**
   ```python
   >>> sf.refresh_from_db()
   >>> sf.ingestion_runs.count()
   1  # IngestionRun created
   >>> run = sf.ingestion_runs.first()
   >>> run.status
   'running'  # Will become 'success' after chunking completes
   >>> sf.artifacts.count()
   1  # Artifact created with extracted text
   >>> artifact = sf.artifacts.first()
   >>> artifact.text
   'This is a test file for Collection upload'
   ```

### Expected Behavior

1. **Upload** → SourceFile created, file saved to storage, returns immediately
2. **15 seconds later** → Celery Beat triggers process_pending_uploads
3. **Processing** → Text extracted, Artifact created, chunking queued
4. **Few seconds later** → Chunking completes, embeddings generated, IngestionRun status = 'success'

## Next Steps (Phase 2 & 3)

### Phase 2: Frontend Integration
- Update FileUpload component to use Collection upload endpoint when in Collection context
- Or create separate CollectionFileUpload component
- Update CollectionBrowser to use new endpoint

### Phase 3: Status Indicator
- Create sparkle status component (like SummarySection pattern)
- Add to CollectionDetailWorkArea header
- Show "Indexing N files..." when processing > 0
- Fade to "Search ready ✓" when complete

## Notes

- Files are stored in Django default_storage (local filesystem or S3/etc based on settings)
- Deduplication works per-library using SHA-256 hash
- Task processes up to 10 files per 15-second cycle to avoid overload
- Text extraction supports: txt, md, json, csv, html, xml, yaml, pdf, docx
- Unsupported file types get placeholder text
