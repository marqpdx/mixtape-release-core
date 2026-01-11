# Testing Standards and Plan

This document defines the testing strategy, suite structure, and the current
formalized test plan for Collections with folders and drag-and-drop reorder.

## Strategy

- Tests are grouped by layer: model, API, integration, and performance (optional).
- Favor deterministic fixtures and isolated data per test case.
- Prefer real integrations unless mocking is required to isolate failures.
- Use `mixtape.settings.test` and `.env.test` for all test runs.
- Reset test DB before suite runs when applicable.

## Suite Structure

- App-level tests live under each app's `tests/` package.
- Cross-app guidance and summaries live in `_testing/`.
- This document anchors standards and primary plans.

## Environment and Data

- Database: `crossroads_test` with `test_user` and restricted permissions.
- Settings: `DJANGO_SETTINGS_MODULE=mixtape.settings.test`.
- DB reset guard: abort if DB name does not contain `test`.
- Expected services up for full-suite runs.

## Collection Items with Folders and Reorder

Scope: LibraryItem model, collection APIs, and reorder endpoint.

### 1) Model Validation Tests

- Folder creation: `is_folder=True`, no content, title required.
- Folder cannot have `content_type` or `content_object_id`.
- Non-folder requires content fields.
- Max nesting depth is 3 (root -> section -> subsection).
- Items can only be nested under folders.
- Prevent circular references (self or ancestor).
- Parent must be within the same collection.
- Delete folder behavior: CASCADE on children (verify current behavior).

### 2) Collection API Tests

- `GET /api/collections/` list filters, counts, and auth.
- `GET /api/collections/{id}/` detail and ingestion status.
- `PATCH /api/collections/{id}/` field updates and validations.
- `GET /api/collections/{id}/available-files/` in-collection flags and counts.

### 3) LibraryItem API Tests

- `GET /api/collections/{id}/items/` ordering, filters, embedded source file.
- `POST /api/collections/{id}/items/` minimal and full create.
- `PATCH /api/collections/{id}/items/{item_id}/` individual and multi-field updates.
- `DELETE /api/collections/{id}/items/{item_id}/` delete without removing SourceFile.

### 4) Reorder API Tests

- Reorder items at root.
- Move item into folder (`parent_id=folder`).
- Move item to root (`parent_id=null`).
- Reject nesting under non-folder (400).
- Reject exceeding max depth (400).
- Parent not found (404).
- Item not found (400/404).
- Reject cross-collection items.
- Transaction rollback on partial failure.

### 5) Edge and Integrity Tests

- Duplicate item at same position (unique constraint).
- Long folder path (limit), large tags arrays, empty values.
- Orphan handling after parent deletion (verify CASCADE).

### 6) Integration Tests

- Create collection -> add items -> reorder -> verify order.
- Same file at different positions allowed.
- Delete item -> available-files count decrements.
- Add item -> collection `item_count` increments.

### 7) Performance Tests (Optional)

- 1000+ items list performance.
- Bulk reorder 100+ items within target duration.

## Permissions and Separation

- App-level tests are expected to pass with local services running.
- Integration tests can be split into a separate run target later.
- Permissions tests will be expanded once authorization is finalized.
