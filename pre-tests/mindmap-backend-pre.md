# Pre-Test Plan: MindMap Backend API

**Feature:** MindMap spatial graph — Models, Services, API (Phases 1-2)
**Date:** 2026-02-26
**Module:** `mindmap/`
**Test file:** `mindmap/tests/test_mindmap_api.py`

---

## What was built

### Models
- `MindMap` (BaseContent) — status, viewport, version, share_mode, share_token
- `MindMapNode` (BaseModel) — hybrid backing (inline/leaf), position, style, inline content
- `MindMapEdge` (BaseModel) — source/target nodes, edge_type, label, directed
- `MindMapNodeAttachment` (BaseModel) — kind (url/image/file/embed/reference), asset FK

### Services
- `mindmap_service` — create_mindmap, update_mindmap, bump_version (atomic F expression)
- `node_service` — create/update/delete/bulk_upsert/bulk_delete/restore with version bump logic
- `edge_service` — create/update/delete/bulk_upsert/bulk_delete with version bump logic

### Endpoints
- `GET/POST /api/mindmaps/` — list/create
- `GET/PATCH /api/mindmaps/{id}/` — detail/update
- `GET/POST /api/mindmaps/{id}/nodes/` — list/create nodes
- `PATCH/DELETE /api/mindmaps/{id}/nodes/{node_id}/` — update/delete node
- `POST /api/mindmaps/{id}/nodes/bulk_upsert/` — bulk create/update nodes
- `POST /api/mindmaps/{id}/nodes/bulk_delete/` — bulk soft-delete nodes
- `GET/POST /api/mindmaps/{id}/edges/` — list/create edges
- `PATCH/DELETE /api/mindmaps/{id}/edges/{edge_id}/` — update/delete edge
- `POST /api/mindmaps/{id}/edges/bulk_upsert/` — bulk create/update edges
- `POST /api/mindmaps/{id}/edges/bulk_delete/` — bulk soft-delete edges
- `GET/POST /api/mindmaps/{id}/nodes/{node_id}/attachments/` — list/create attachments
- `PATCH/DELETE /api/mindmaps/{id}/nodes/{node_id}/attachments/{att_id}/` — update/delete attachment

---

## Test Suite Plan

### A. MindMap CRUD

| # | Test | Assert |
|---|------|--------|
| 1 | `test_create_mindmap` | 201, returns id/title/slug/version=0 |
| 2 | `test_create_mindmap_default_status_draft` | status is "draft" |
| 3 | `test_create_mindmap_slug_generated_from_title` | slug is slugified title |
| 4 | `test_list_mindmaps_only_own` | 200, only returns user's mindmaps |
| 5 | `test_list_excludes_deleted` | Soft-deleted mindmaps not returned |
| 6 | `test_get_mindmap_detail` | 200, includes viewport, node_count, edge_count |
| 7 | `test_get_mindmap_detail_counts_exclude_deleted` | node_count/edge_count exclude soft-deleted |
| 8 | `test_patch_mindmap_title` | title updated, slug auto-regenerated if provisional |
| 9 | `test_patch_mindmap_viewport` | viewport JSON saved, version NOT bumped |
| 10 | `test_patch_mindmap_status` | status updated |
| 11 | `test_create_mindmap_unauthenticated` | 401 |
| 12 | `test_get_other_users_mindmap_denied` | 403 (not the owner) |

### B. Node CRUD

| # | Test | Assert |
|---|------|--------|
| 1 | `test_create_node` | 201, node returned with all fields |
| 2 | `test_create_node_bumps_version` | mindmap.version increments by 1 |
| 3 | `test_create_inline_node` | backing_kind=inline, title/text stored |
| 4 | `test_create_leaf_backed_node` | backing_kind=leaf, leaf FK set |
| 5 | `test_list_nodes` | 200, returns all non-deleted nodes with attachments |
| 6 | `test_list_nodes_excludes_deleted` | Soft-deleted nodes not returned |
| 7 | `test_patch_node_position_no_version_bump` | pos_x/pos_y updated, version unchanged |
| 8 | `test_patch_node_style_no_version_bump` | style updated, version unchanged |
| 9 | `test_patch_node_title_bumps_version` | title updated, version bumped |
| 10 | `test_patch_node_text_bumps_version` | text updated, version bumped |
| 11 | `test_patch_node_backing_kind_bumps_version` | backing_kind changed, version bumped |
| 12 | `test_delete_node_soft_deletes` | deleted_at set, node excluded from list |
| 13 | `test_delete_node_bumps_version` | version incremented |
| 14 | `test_delete_node_cascades_to_edges` | connected edges also soft-deleted |
| 15 | `test_node_wrong_mindmap_404` | 404 for node belonging to different mindmap |

### C. Node Bulk Operations

| # | Test | Assert |
|---|------|--------|
| 1 | `test_bulk_upsert_create_nodes` | New nodes created, ids returned |
| 2 | `test_bulk_upsert_update_nodes` | Existing nodes updated by id |
| 3 | `test_bulk_upsert_mixed_create_update` | Both creates and updates in one call |
| 4 | `test_bulk_upsert_position_only_no_version_bump` | Items with only id+pos_x+pos_y, version unchanged |
| 5 | `test_bulk_upsert_title_edit_bumps_version` | Title change in bulk, version bumped once |
| 6 | `test_bulk_upsert_single_version_bump` | Multiple creates = one version increment |
| 7 | `test_bulk_upsert_minimal_payload` | Item with only id + pos is valid, doesn't null other fields |
| 8 | `test_bulk_upsert_not_found_returns_error` | Non-existent id returns ok=false per item |
| 9 | `test_bulk_upsert_empty_items_rejected` | 400, items list required |
| 10 | `test_bulk_delete_nodes` | Nodes soft-deleted, count returned |
| 11 | `test_bulk_delete_cascades_edges` | Connected edges also soft-deleted |
| 12 | `test_bulk_delete_returns_version` | Response includes new version |
| 13 | `test_bulk_delete_empty_ids_rejected` | 400, ids list required |
| 14 | `test_bulk_delete_nonexistent_ids_zero_count` | Already-deleted ids return deleted=0, no version bump |

### D. Edge CRUD

| # | Test | Assert |
|---|------|--------|
| 1 | `test_create_edge` | 201, edge returned with source/target/type |
| 2 | `test_create_edge_bumps_version` | version incremented |
| 3 | `test_create_edge_validates_nodes_in_mindmap` | 404 if source/target node not in this mindmap |
| 4 | `test_list_edges` | 200, all non-deleted edges |
| 5 | `test_list_edges_excludes_deleted` | Soft-deleted edges not returned |
| 6 | `test_patch_edge_label_bumps_version` | Semantic edit, version bumped |
| 7 | `test_patch_edge_style_no_version_bump` | Style-only edit, version unchanged |
| 8 | `test_delete_edge_soft_deletes` | deleted_at set |
| 9 | `test_delete_edge_bumps_version` | version incremented |
| 10 | `test_edge_wrong_mindmap_404` | 404 for edge belonging to different mindmap |

### E. Edge Bulk Operations

| # | Test | Assert |
|---|------|--------|
| 1 | `test_bulk_upsert_create_edges` | New edges created, ids returned |
| 2 | `test_bulk_upsert_update_edges` | Existing edges updated |
| 3 | `test_bulk_upsert_single_version_bump` | One version increment for batch |
| 4 | `test_bulk_upsert_empty_items_rejected` | 400 |
| 5 | `test_bulk_delete_edges` | Edges soft-deleted, count + version returned |
| 6 | `test_bulk_delete_empty_ids_rejected` | 400 |

### F. Attachment CRUD

| # | Test | Assert |
|---|------|--------|
| 1 | `test_create_attachment` | 201, attachment created on node |
| 2 | `test_create_attachment_bumps_version` | version incremented |
| 3 | `test_list_attachments` | 200, non-deleted attachments for node |
| 4 | `test_patch_attachment` | Fields updated, version bumped |
| 5 | `test_delete_attachment_soft_deletes` | deleted_at set, version bumped |
| 6 | `test_attachment_wrong_node_404` | 404 for attachment on different node |

### G. Version Bump Rules (Appendix C compliance)

| # | Test | Assert |
|---|------|--------|
| 1 | `test_version_bumps_on_node_create` | YES |
| 2 | `test_version_bumps_on_node_delete` | YES |
| 3 | `test_version_bumps_on_edge_create` | YES |
| 4 | `test_version_bumps_on_edge_delete` | YES |
| 5 | `test_version_bumps_on_inline_edit` | YES (title/text/primary_url) |
| 6 | `test_version_bumps_on_backing_kind_change` | YES |
| 7 | `test_version_bumps_on_edge_semantic_edit` | YES (edge_type/label/meta) |
| 8 | `test_version_bumps_on_attachment_add` | YES |
| 9 | `test_version_bumps_on_attachment_remove` | YES |
| 10 | `test_no_version_bump_on_position_change` | NO |
| 11 | `test_no_version_bump_on_viewport_change` | NO |
| 12 | `test_no_version_bump_on_style_change` | NO (node or edge) |
| 13 | `test_version_atomic_increment` | F('version') + 1, concurrent-safe |

### H. Permission / Ownership Tests

| # | Test | Assert |
|---|------|--------|
| 1 | `test_unauthenticated_all_endpoints_401` | 401 for all endpoints |
| 2 | `test_other_user_mindmap_list_empty` | Other user sees empty list |
| 3 | `test_other_user_mindmap_detail_403` | 403 on detail/patch |
| 4 | `test_other_user_node_operations_403` | 403 on CRUD/bulk for other's mindmap |
| 5 | `test_other_user_edge_operations_403` | 403 on CRUD/bulk for other's mindmap |
| 6 | `test_other_user_attachment_operations_403` | 403 on attachment CRUD |

### I. Soft Delete Integrity

| # | Test | Assert |
|---|------|--------|
| 1 | `test_deleted_mindmap_not_in_list` | Excluded from GET list |
| 2 | `test_deleted_node_not_in_list` | Excluded from GET nodes |
| 3 | `test_deleted_edge_not_in_list` | Excluded from GET edges |
| 4 | `test_deleted_attachment_not_in_list` | Excluded from GET attachments |
| 5 | `test_delete_node_cascade_edge_integrity` | Edges cascade-deleted match source/target |
| 6 | `test_bulk_delete_node_cascade_edge_integrity` | Bulk delete cascades correctly |

---

## Fixture Requirements

- **Users:** `owner` (mindmap creator), `other_user` (no access), `staff_user` (optional)
- **MindMap:** One user-sponsored mindmap, one from other_user for permission tests
- **Nodes:** Multiple nodes (inline note, inline link, leaf-backed), one soft-deleted
- **Edges:** Edges connecting nodes, one soft-deleted
- **Attachments:** URL and image attachments on a node
- **Leaf:** One Leaf instance for leaf-backed node tests

## Dependencies

- `fundamentals.bases.BaseModel` — soft-delete via `deleted_at`
- `fundamentals.models.BaseContent` — sponsor GFK, slug lifecycle, UUID PK
- `writing.models.Leaf` — FK target for leaf-backed nodes
- `files.models.StoredFile` — FK target for asset attachments
- `utils.shared.contenttypes.resolve_content_type` — sponsor type resolution

## Run Command

```bash
python manage.py test mindmap.tests --settings=mixtape.settings.test -v 2
```
