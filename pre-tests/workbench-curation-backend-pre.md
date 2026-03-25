# Pre-Test Plan: Workbench Curation API

**Feature:** Four-lane curation workbench — Working Items, Unified Pieces, Promotion
**Date:** 2026-03-24
**Module:** `workbench/`
**Test files:** `workbench/tests/test_working_items_api.py`, `workbench/tests/test_pieces_api.py`, `workbench/tests/test_promote_api.py`

---

## What was built

- `WorkingItem` model — `BaseContent` subclass with status state machine, fork lock (`body_editing_started`), spellcheck gate, promotion provenance (`promoted_to`, `promoted_at`)
- `WorkingItemMembership` — polymorphic GFK audit record linking raw Pieces to WorkingItems; immutable once fork lock is set
- `UnifiedPieceListView` — `GET /api/groups/<slug>/workbench/pieces` — aggregates Seeds, Leaves, MillDrafts, FeedbackItems, WorkingDocuments into a normalised `Piece` shape
- `WorkingItemListCreateView` — `GET/POST /api/groups/<slug>/workbench/working-items`
- `WorkingItemDetailView` — `GET/PATCH/DELETE /api/groups/<slug>/workbench/working-items/<item_id>`
- `WorkingItemAutosaveView` — `PATCH /api/groups/<slug>/workbench/working-items/<item_id>/autosave`
- `WorkingItemMembershipView` — `POST/DELETE /api/groups/<slug>/workbench/working-items/<item_id>/pieces[/<membership_id>]`
- `WorkingItemPromoteView` — `POST /api/groups/<slug>/workbench/working-items/<item_id>/promote`
- Promotion gates: hard (`title_required`, `status_ready`), soft (`spellcheck`)
- All endpoints: superuser-only for v0

---

## Test Suite Plan

### A. WorkingItem List & Create

| # | Test | Assert |
|---|------|--------|
| 1 | `test_list_working_items_empty` | GET → 200, empty list |
| 2 | `test_list_working_items_returns_group_items_only` | Items for other groups not included |
| 3 | `test_list_filter_by_status_assembling` | `?status=assembling` returns only matching items |
| 4 | `test_list_filter_by_status_ready` | `?status=ready` returns only ready items |
| 5 | `test_list_filter_excludes_promoted_by_default` | Promoted items absent unless explicitly filtered |
| 6 | `test_create_working_item_minimal` | POST with title → 201, item returned with status=assembling |
| 7 | `test_create_stitches_body_json_from_pieces` | POST with `piece_ids` → body_json contains piece content in order |
| 8 | `test_create_creates_memberships` | Each piece_id produces a WorkingItemMembership record |
| 9 | `test_create_missing_title_allowed` | POST with empty title → 201 (title is soft-gated, not required at create) |
| 10 | `test_create_non_superuser_rejected` | POST as regular admin → 403 |
| 11 | `test_create_unauthenticated` | POST unauthenticated → 401 |

### B. WorkingItem Detail — Read, Update, Delete

| # | Test | Assert |
|---|------|--------|
| 1 | `test_get_working_item` | GET → 200, includes memberships list |
| 2 | `test_get_wrong_group_404` | GET item from different group → 404 |
| 3 | `test_patch_status_assembling_to_ready` | PATCH `{status: "ready"}` → 200, status updated |
| 4 | `test_patch_title` | PATCH `{title: "New Title"}` → 200 |
| 5 | `test_patch_target_writing_kind` | PATCH `{target_writing_kind: "essay"}` → 200 |
| 6 | `test_patch_disallowed_field_ignored` | PATCH `{promoted_at: "..."}` → field not changed |
| 7 | `test_patch_promoted_item_blocked` | PATCH on item with status=promoted → 400 |
| 8 | `test_delete_soft_deletes` | DELETE → 204, `deleted_at` is set |
| 9 | `test_delete_promoted_item_blocked` | DELETE on promoted item → 400 |
| 10 | `test_delete_absent_from_list_after_soft_delete` | Deleted item not in list response |

### C. Autosave + Fork Lock

| # | Test | Assert |
|---|------|--------|
| 1 | `test_autosave_body_json` | PATCH body_json → 200, `last_saved_at` updated |
| 2 | `test_autosave_increments_auto_save_count` | Successive autosaves increment counter |
| 3 | `test_autosave_sets_fork_lock_on_first_body_edit` | `body_editing_started` becomes True after first body_json patch |
| 4 | `test_autosave_fork_lock_idempotent` | Second body patch does not flip fork lock back |
| 5 | `test_autosave_title_does_not_set_fork_lock` | PATCH title only → `body_editing_started` stays False |
| 6 | `test_autosave_body_change_resets_spellcheck` | If `spellcheck_passed=True`, body patch clears it |
| 7 | `test_autosave_title_only_does_not_reset_spellcheck` | Title-only patch does not clear spellcheck |
| 8 | `test_autosave_promoted_item_blocked` | PATCH on promoted item → 400 |

### D. Membership — Add & Remove Pieces

| # | Test | Assert |
|---|------|--------|
| 1 | `test_add_piece_creates_membership` | POST → 201, WorkingItemMembership created |
| 2 | `test_add_piece_snapshot_captured` | `content_snapshot` is non-empty string |
| 3 | `test_add_piece_position_appended` | New membership has `position` = len(existing memberships) |
| 4 | `test_add_duplicate_piece` | POST same piece twice → 400 (or membership reused; assert deterministic) |
| 5 | `test_add_piece_after_fork_lock_allowed` | Pieces can still be added when `body_editing_started=True` |
| 6 | `test_remove_piece_before_fork_lock` | DELETE membership → 204, record removed |
| 7 | `test_remove_piece_after_fork_lock_blocked` | DELETE → 400, "Assembly order is locked" |
| 8 | `test_remove_nonexistent_membership_404` | DELETE unknown membership_id → 404 |
| 9 | `test_remove_membership_wrong_item_404` | DELETE membership belonging to a different item → 404 |

### E. Unified Pieces Endpoint

| # | Test | Assert |
|---|------|--------|
| 1 | `test_pieces_returns_seeds` | Seeds authored by group members appear in result |
| 2 | `test_pieces_returns_leaves` | Leaves appear |
| 3 | `test_pieces_returns_milldrafts` | Group-sponsored MillDrafts with status not in (promoted, archived) appear |
| 4 | `test_pieces_milldraft_promoted_excluded` | MillDraft with status=promoted not returned |
| 5 | `test_pieces_returns_working_documents` | Draft WritingPieces (working documents) sponsored by group appear |
| 6 | `test_pieces_filter_by_type_seed` | `?type=seed` returns only seeds |
| 7 | `test_pieces_filter_by_type_milldraft` | `?type=milldraft` returns only mill drafts |
| 8 | `test_pieces_search_query` | `?q=keyword` filters by title/content substring |
| 9 | `test_pieces_ungrouped_filter` | `?ungrouped=true` excludes pieces already in a working item |
| 10 | `test_pieces_working_item_references` | Each piece includes `working_item_references` list of item IDs |
| 11 | `test_pieces_seeds_scoped_to_group_members` | Seed authored by non-member not returned |
| 12 | `test_pieces_non_superuser_rejected` | 403 for regular admin |
| 13 | `test_pieces_unauthenticated` | 401 |

### F. Promotion — Gate Evaluation & Execute

| # | Test | Assert |
|---|------|--------|
| 1 | `test_promote_hard_gate_title_required` | POST with no title → 400, `failures` contains `title_required` with `hard=true` |
| 2 | `test_promote_hard_gate_status_not_ready` | POST with status=assembling → 400, `failures` contains `status_ready` |
| 3 | `test_promote_soft_gate_spellcheck` | POST with `spellcheck_passed=False` → 400, warnings contain `spellcheck` with `hard=false` |
| 4 | `test_promote_soft_gate_override` | POST with `override_soft_gates=true` → 201, promoted despite spellcheck |
| 5 | `test_promote_all_gates_pass` | POST with valid item (title + ready + spellcheck) → 201 |
| 6 | `test_promote_creates_writing_piece` | WritingPiece exists with `status=draft` after promotion |
| 7 | `test_promote_creates_working_document` | WorkingDocument exists linked to WritingPiece |
| 8 | `test_promote_atomic` | If WritingPiece creation fails, WorkingItem status not changed |
| 9 | `test_promote_marks_working_item_promoted` | `working_item.status == "promoted"`, `promoted_to` FK set, `promoted_at` set |
| 10 | `test_promote_returns_ids` | 201 response includes `writing_piece_id`, `working_document_id`, `working_item_id` |
| 11 | `test_promote_already_promoted_blocked` | POST on already-promoted item → 400 |
| 12 | `test_promote_non_superuser_rejected` | 403 for regular admin |

### G. Permission Checks (cross-cutting)

| # | Test | Assert |
|---|------|--------|
| 1 | `test_all_endpoints_require_superuser` | GET/POST/PATCH/DELETE on all workbench endpoints → 403 for group admin |
| 2 | `test_all_endpoints_reject_anonymous` | 401 for unauthenticated requests on all routes |
| 3 | `test_superuser_can_access_any_group` | Superuser can operate on items for groups they are not a member of |

---

## Fixture Requirements

- **Users:** `superuser`, `group_admin` (admin role in group, not superuser), `outsider`
- **Group:** `test_group` with active memberships for group_admin
- **Seeds / Leaves / MillDrafts:** At least one of each, authored by `group_admin` (a group member)
- **WorkingItem:** One `assembling` item (no fork lock), one `ready` item (with title + spellcheck), one `promoted` item
- **WorkingItemMembership:** Two memberships on the assembling item; one with fork lock set

## Dependencies

- `workbench.models.WorkingItem`, `WorkingItemMembership`
- `workbench.api.promotion._evaluate_gates` — gates logic under test
- `writing.models.WritingPiece`, `writing.models.WorkingDocument` — created on promotion
- `groups.services.permissions.PermissionService` — `is_superuser` check for v0

## Run Command

```bash
python manage.py test workbench.tests --settings=mixtape.settings.test -v 2
```
