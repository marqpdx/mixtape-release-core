# Copy Desk Intelligence — Backend Pre-Test

**Feature:** Copy Desk Intelligence — word count goals, AI split suggestions, split execution
**Date:** 2026-04-02
**Module:** `writing/`, `worksessions/`
**Migrations:** `writing/0014_writingpiece_wordcount_goal.py`, `writing/0015_splitssuggestion.py`
**Frontend test plan:** `mixtape-release-frontend/pre-tests/copy-desk-intelligence-frontend-pre.md`

---

## What was built

### Models
- `WritingPiece.target_wordcount` — soft word count goal (null = none set)
- `WritingPiece.suggest_splits` — opt-in flag; auto-cleared when user declines
- `SplitSuggestion` — AI-generated split proposal; statuses: `pending → ready → shown → accepted/dismissed/declined/executed/superseded`
- `WorkSession`, `WritingSurfaceDocument`, `WorkSessionItem`, `ArtifactMergeRecord` — pre-existing in `worksessions/`

### Endpoints
- `GET  /api/writing/pieces/<pk>/split-suggestion` — current non-terminal suggestion
- `POST /api/writing/pieces/<pk>/split-suggestion` — act: `view | dismiss | decline`
- `POST /api/writing/pieces/<pk>/execute-split` — deterministic split execution

### Service
- `writing/split_service.py:execute_split(piece, user)` — parses `splitMarker` nodes, creates pieces, builds `WorkSession` + `WritingSurfaceDocument`

### Tasks
- `generate_split_suggestion_task` — Celery task; calls AI to identify split points; updates `SplitSuggestion` to `ready`

### Permissions
- `CanEditWritingPiece` — author or staff; enforced on all three endpoints

---

## Preconditions (setUp)

- `author` — owns the `WritingPiece` under test
- `other_user` — authenticated but not the author
- `WritingPiece` with `suggest_splits=True`, `target_wordcount=400`
- `WorkingDocument` for `(piece, author)` with `body_json` containing realistic content
- Celery worker available for task tests (or use `apply()` directly in test)
- For execute-split tests: `WorkingDocument.body_json` must contain `splitMarker` nodes

---

## A) Split Suggestion — Autosave Trigger

| # | Test | Assert |
|---|------|--------|
| A1 | `test_autosave_queues_suggestion_when_over_threshold` | Saving a working copy at 115% of `target_wordcount` creates a `SplitSuggestion` with `status="pending"` and queues `generate_split_suggestion_task` |
| A2 | `test_autosave_no_suggestion_when_under_threshold` | Saving at 114% does not create a suggestion |
| A3 | `test_autosave_no_suggestion_when_suggest_splits_false` | `suggest_splits=False` — no suggestion created even at 200% |
| A4 | `test_autosave_no_suggestion_when_no_target` | `target_wordcount=None` — no suggestion |
| A5 | `test_autosave_does_not_duplicate_pending_suggestion` | A second autosave while a `pending` suggestion exists does not create another |
| A6 | `test_autosave_supersedes_ready_suggestion` | A second trigger (e.g. word count grew again) supersedes any `ready/shown` suggestion and creates a new `pending` one |
| A7 | `test_autosave_returns_current_status_in_response` | Response from working-copy PUT includes `split_suggestion_status` key |

---

## B) Split Suggestion — Status Transitions

| # | Test | Assert |
|---|------|--------|
| B1 | `test_get_suggestion_returns_none_when_no_suggestion` | `GET` → `{"status": null, "suggestions": []}` |
| B2 | `test_get_suggestion_returns_ready_suggestion` | `GET` on piece with `ready` suggestion → returns it |
| B3 | `test_post_action_view_transitions_to_shown` | `POST {"action": "view"}` on `ready` → `status="shown"`, `suggestions` list returned |
| B4 | `test_post_action_dismiss_transitions_to_dismissed` | `POST {"action": "dismiss"}` → `status="dismissed"`, `suggest_splits` unchanged |
| B5 | `test_post_action_decline_transitions_to_declined` | `POST {"action": "decline"}` → `status="declined"`, `piece.suggest_splits=False` |
| B6 | `test_post_action_invalid_rejected` | `POST {"action": "accept"}` → `400` |
| B7 | `test_post_no_actionable_suggestion_returns_404` | `POST` when suggestion is `pending` (not ready) → `404` |
| B8 | `test_get_excludes_executed_suggestions` | `executed` suggestion does not appear in `GET` |
| B9 | `test_get_excludes_declined_suggestions` | `declined` suggestion does not appear in `GET` |

---

## C) Execute Split — Happy Path

| # | Test | Assert |
|---|------|--------|
| C1 | `test_execute_split_single_marker` | Working copy with 1 `splitMarker` node → `201`, creates 1 new `WritingPiece`, `WorkSession` with 1 item |
| C2 | `test_execute_split_multiple_markers` | Working copy with 2 `splitMarker` nodes → creates 2 new pieces, `WorkSession` with 2 items |
| C3 | `test_execute_split_sets_new_piece_title_from_marker` | Marker attrs have `title="Part Two"` → new piece `title="Part Two"` |
| C4 | `test_execute_split_untitled_marker` | Marker `title=null` → new piece `title=""` |
| C5 | `test_execute_split_response_shape` | Response has `session_id`, `surface_body_json`, `new_piece_ids` |
| C6 | `test_execute_split_surface_doc_has_segment_boundaries` | `surface_body_json.content` contains `segmentBoundary` nodes at expected positions |
| C7 | `test_execute_split_anchor_working_copy_trimmed` | After execution, working copy `body_json` contains only pre-split nodes |
| C8 | `test_execute_split_marks_suggestion_executed` | Any active `SplitSuggestion` for the piece transitions to `executed` |
| C9 | `test_execute_split_new_pieces_inherit_sponsor` | New pieces have same `sponsor_content_type`/`sponsor_object_id` as original |
| C10 | `test_execute_split_new_pieces_inherit_writing_kind` | New pieces have same `writing_kind` |
| C11 | `test_execute_split_creates_work_session_items` | `WorkSessionItem` rows created for each new piece, with sequential `sequence` values |

---

## D) Execute Split — Error Cases

| # | Test | Assert |
|---|------|--------|
| D1 | `test_execute_split_no_working_copy` | No `WorkingDocument` for this user → `400` with detail |
| D2 | `test_execute_split_no_markers` | Working copy has no `splitMarker` nodes → `400` "No split markers found" |
| D3 | `test_execute_split_as_other_user` | `other_user` requests split → `403` |
| D4 | `test_execute_split_unauthenticated` | No auth → `401` |
| D5 | `test_execute_split_nonexistent_piece` | Random UUID → `404` |

---

## E) WorkSession Integration

| # | Test | Assert |
|---|------|--------|
| E1 | `test_work_session_anchor_is_original_piece` | `session.anchor_content_type.model == "writingpiece"`, `session.anchor_object_id == piece.pk` |
| E2 | `test_work_session_owner_is_requesting_user` | `session.owner == author` |
| E3 | `test_work_session_is_active` | `session.ended_at is None`, `session.is_active == True` |
| E4 | `test_surface_document_body_roundtrips` | `_parse_segments()` on the surface body returns correct anchor and emitted segments |
| E5 | `test_checkpoint_after_execute_updates_pieces` | Calling `checkpoint_extraction(session)` with modified surface body updates both anchor and new pieces' working copies |

---

## Deliverables

**Success response from `POST /api/writing/pieces/<pk>/execute-split`:**
```json
{
  "session_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "surface_body_json": {
    "type": "doc",
    "content": [
      {"type": "paragraph", "content": [{"type": "text", "text": "First part content."}]},
      {"type": "segmentBoundary", "attrs": {"artifactType": "writingpiece", "artifactId": "<new-piece-uuid>", "isAnchorReturn": false}},
      {"type": "paragraph", "content": [{"type": "text", "text": "Second part content."}]}
    ]
  },
  "new_piece_ids": ["<new-piece-uuid>"]
}
```

**No markers — `400`:**
```json
{"detail": "No split markers found in working copy."}
```

**Unauthorized — `403`:**
```json
{"detail": "You do not have permission to perform this action."}
```

---

## Notes

- `splitMarker` nodes in working copy JSON look like:
  `{"type": "splitMarker", "attrs": {"markerId": "...", "source": "manual", "title": null, "rationale": null}}`
- The autosave threshold is 15% over `target_wordcount` (`word_count >= target * 1.15`).
- `decline` action sets `piece.suggest_splits=False` — verified by a subsequent autosave not queuing a new suggestion even when over threshold.
- Execute-split does NOT require an active `SplitSuggestion` — it works on any piece with split markers in the working copy.
- All write operations in `execute_split` are wrapped in `@transaction.atomic`.
