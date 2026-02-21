# Dispatch Comments — Backend Test Plan

**Feature:** Inline Editorial Comments for Dispatch Writing
**Date:** 2026-02-20
**Modules:** `dispatch/`
**Test file:** `dispatch/tests/test_comments.py`

---

## What will be built

### Backend
- `DispatchComment` model: block-anchored, threaded, with resolve workflow
- API endpoints:
  - `GET /api/dispatch/comments/{piece_id}` — list comments (threaded)
  - `POST /api/dispatch/comments` — create comment
  - `PATCH /api/dispatch/comments/{comment_id}` — edit body
  - `DELETE /api/dispatch/comments/{comment_id}` — delete
  - `POST /api/dispatch/comments/{comment_id}/resolve` — resolve
  - `POST /api/dispatch/comments/{comment_id}/unresolve` — unresolve
- Permission helpers: `_can_comment()`, `_can_resolve()`

### Frontend (not covered in this test plan)
- Comment highlights, CopyDesk integration, gutter indicators

---

## Preconditions (setUp)

- Create users `author`, `editor_user`, `commenter_user`, `outsider`.
- Create a `WritingPiece` owned by `author`, `writing_kind = dispatch`.
- Create a `WorkingDocument` for the piece.
- Attach `DispatchContent` to the WorkingDocument.
- Add `editor_user` as collaborator with role `editor`.
- Add `commenter_user` as collaborator with role `commenter`.
- Mock activity producers (`on_comment_created`, etc.).

---

## A) Create Comment

| # | Test | Assert |
|---|------|--------|
| 1 | `test_create_comment_as_author` | `201`, comment created with correct `writing_piece`, `author`, `body` |
| 2 | `test_create_comment_as_editor` | `201`, editor can comment |
| 3 | `test_create_comment_as_commenter` | `201`, commenter can comment |
| 4 | `test_create_comment_as_outsider` | `403` |
| 5 | `test_create_comment_unauthenticated` | `401` |
| 6 | `test_create_comment_with_block_id` | `201`, `block_id` saved correctly |
| 7 | `test_create_comment_with_text_range` | `201`, `anchor_from`, `anchor_to`, `quoted_text` saved |
| 8 | `test_create_comment_without_block_id` | `201`, general comment (no anchor) |
| 9 | `test_create_comment_empty_body_rejected` | `400`, body is required |

---

## B) Reply Threading

| # | Test | Assert |
|---|------|--------|
| 1 | `test_create_reply` | `201`, `parent_id` set, appears in parent's `replies` list |
| 2 | `test_reply_inherits_piece` | Reply's `writing_piece` matches parent's piece (enforced) |
| 3 | `test_reply_to_wrong_piece_rejected` | `400`, parent must belong to same piece |
| 4 | `test_nested_replies` | Reply to a reply works, tree structure correct in GET |

---

## C) List Comments

| # | Test | Assert |
|---|------|--------|
| 1 | `test_list_comments_as_author` | `200`, returns threaded comment tree |
| 2 | `test_list_comments_as_collaborator` | `200`, same result |
| 3 | `test_list_comments_as_outsider` | `403` |
| 4 | `test_list_includes_counts` | Response includes `counts.total`, `counts.open`, `counts.resolved` |
| 5 | `test_list_ordered_by_created_at` | Root comments ordered by `created_at` ascending |
| 6 | `test_list_groups_by_block` | Comments grouped/filterable by `block_id` |

---

## D) Edit Comment

| # | Test | Assert |
|---|------|--------|
| 1 | `test_edit_own_comment` | `200`, body updated |
| 2 | `test_edit_others_comment_denied` | `403`, can only edit own |
| 3 | `test_edit_preserves_anchors` | After PATCH, `block_id`, `anchor_from`, `anchor_to` unchanged |

---

## E) Delete Comment

| # | Test | Assert |
|---|------|--------|
| 1 | `test_delete_own_comment` | `204`, comment removed |
| 2 | `test_delete_others_comment_as_author` | `204`, piece author can delete any comment |
| 3 | `test_delete_others_comment_as_commenter` | `403`, commenter can't delete others' comments |
| 4 | `test_delete_parent_with_replies` | Decide: cascade delete replies, or orphan them? |

---

## F) Resolve/Unresolve

| # | Test | Assert |
|---|------|--------|
| 1 | `test_resolve_as_author` | `200`, `is_resolved=True`, `resolved_by` set, `resolved_at` set |
| 2 | `test_resolve_as_editor` | `200`, editors can resolve |
| 3 | `test_resolve_as_commenter_denied` | `403`, commenters cannot resolve |
| 4 | `test_unresolve` | `200`, `is_resolved=False`, `resolved_by=None`, `resolved_at=None` |
| 5 | `test_resolve_already_resolved` | `200` (idempotent, no error) |
| 6 | `test_unresolve_not_resolved` | `200` (idempotent) |

---

## G) Orphaned Comments

| # | Test | Assert |
|---|------|--------|
| 1 | `test_comment_with_nonexistent_block_id` | Comment still accessible via list endpoint |
| 2 | `test_comment_survives_piece_edit` | After body_json changes, comments unchanged |

---

## H) Permission Edge Cases

| # | Test | Assert |
|---|------|--------|
| 1 | `test_comment_on_non_collaborative_piece` | `403` or `400` (no DispatchContent attached) |
| 2 | `test_comment_after_collaborator_removed` | `403` (removed collaborator can't comment) |
| 3 | `test_author_always_has_access` | Author can comment even without DispatchContent |

---

## Deliverables
- Example threaded comment JSON from `GET /api/dispatch/comments/{piece_id}`.
- Permission denial response snippets (`403`).
- Validation error snippets (`400`).
