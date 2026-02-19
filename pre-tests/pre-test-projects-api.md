# Pre-Test Plan: Projects API

**Feature:** Project Board Backend — Columns, Tasks, DnD Support
**Date:** 2026-02-19
**Module:** `projects/`
**Test file:** `projects/tests/test_projects_api.py`

---

## What was built

### Existing Endpoints
- `POST /api/projects/projects` — create project (auto-seeds 5 columns)
- `GET /api/projects/projects/list` — list projects by sponsor
- `GET /api/projects/projects/{id}/board` — full board (columns + tasks_by_column)
- `POST /api/projects/projects/{id}/tasks` — create task in column
- `POST /api/projects/tasks/{id}/move` — move task (within/across columns)

### New Endpoints (this session)
- `PATCH /api/projects/projects/{id}/columns/{id}/toggle-hidden` — toggle column visibility
- `PATCH /api/projects/tasks/{id}` — update task title/summary
- `POST /api/projects/tasks/{id}/archive` — archive task

---

## Test Suite Plan

### A. Project Creation Tests

| # | Test | Assert |
|---|------|--------|
| 1 | `test_create_project_for_group` | 201, project returned with title/slug |
| 2 | `test_create_project_seeds_5_columns` | Board has 5 columns: Backlog, Ready, Doing, Blocked, Done |
| 3 | `test_create_project_column_semantic_types` | Each column has correct semantic_type |
| 4 | `test_create_project_unauthenticated` | 401 |
| 5 | `test_create_project_no_permission` | 403 (non-member of group) |
| 6 | `test_create_project_for_self` | 201, sponsor is user |

### B. Project List Tests

| # | Test | Assert |
|---|------|--------|
| 1 | `test_list_projects_for_group` | 200, returns projects for sponsor |
| 2 | `test_list_excludes_archived` | Archived projects not returned |
| 3 | `test_list_requires_sponsor_params` | 400 without sponsor_type/sponsor_object_id |
| 4 | `test_list_no_permission` | 403 for non-member |

### C. Board View Tests

| # | Test | Assert |
|---|------|--------|
| 1 | `test_get_board` | 200, returns project + columns + tasks_by_column |
| 2 | `test_board_excludes_archived_tasks` | Archived tasks not in tasks_by_column |
| 3 | `test_board_columns_ordered_by_position` | Columns in position order |
| 4 | `test_board_tasks_ordered_by_position` | Tasks within each column sorted by position |
| 5 | `test_board_no_permission` | 403 |

### D. Task Creation Tests

| # | Test | Assert |
|---|------|--------|
| 1 | `test_create_task_default_backlog` | 201, task in backlog column |
| 2 | `test_create_task_specific_column` | 201, task in specified column |
| 3 | `test_create_task_position_auto_increments` | Second task has position > first |
| 4 | `test_create_task_in_hidden_column_rejected` | 400, cannot add to hidden column |
| 5 | `test_create_task_in_done_sets_completed_at` | completed_at is set |
| 6 | `test_create_task_invalid_column` | 400 |
| 7 | `test_create_task_no_permission` | 403 |

### E. Task Move Tests

| # | Test | Assert |
|---|------|--------|
| 1 | `test_move_within_column` | Task reordered, same column |
| 2 | `test_move_across_columns` | Task in new column, positions updated |
| 3 | `test_move_to_done_sets_completed_at` | completed_at set on move to Done |
| 4 | `test_move_from_done_clears_completed_at` | completed_at cleared on move from Done |
| 5 | `test_move_to_hidden_column_rejected` | 400 |
| 6 | `test_move_returns_affected_columns` | Response includes column position data |
| 7 | `test_move_archived_task_404` | 404 for archived task |
| 8 | `test_move_no_permission` | 403 |

### F. Column Toggle Hidden Tests (new)

| # | Test | Assert |
|---|------|--------|
| 1 | `test_toggle_hidden_empty_column` | 200, is_hidden toggled to True |
| 2 | `test_toggle_unhide` | 200, is_hidden toggled back to False |
| 3 | `test_toggle_hidden_column_with_tasks_rejected` | 400, ValidationError (cannot hide with active tasks) |
| 4 | `test_toggle_hidden_column_with_only_archived_tasks` | 200, succeeds (archived don't count) |
| 5 | `test_toggle_hidden_wrong_project` | 404 (column belongs to different project) |
| 6 | `test_toggle_hidden_no_permission` | 403 (requires CanEditProject) |

### G. Task Update Tests (new)

| # | Test | Assert |
|---|------|--------|
| 1 | `test_update_task_title` | 200, title updated |
| 2 | `test_update_task_summary` | 200, summary updated |
| 3 | `test_update_task_both_fields` | 200, both updated |
| 4 | `test_update_task_empty_payload` | 400, "At least one field required" |
| 5 | `test_update_archived_task_404` | 404 |
| 6 | `test_update_task_no_permission` | 403 (requires CanEditTask) |

### H. Task Archive Tests (new)

| # | Test | Assert |
|---|------|--------|
| 1 | `test_archive_task` | 200, archived_at set |
| 2 | `test_archive_task_not_in_board` | Board endpoint excludes archived task |
| 3 | `test_archive_already_archived_404` | 404 (archived_at__isnull=True filter) |
| 4 | `test_archive_task_no_permission` | 403 (requires CanArchiveTask) |

### I. Permission Tests (cross-cutting)

| # | Test | Assert |
|---|------|--------|
| 1 | `test_group_member_can_view_board` | 200 for group member |
| 2 | `test_group_admin_can_edit_project` | Column toggle works for admin |
| 3 | `test_sponsor_user_can_access_own_project` | User-sponsored project accessible |
| 4 | `test_staff_can_access_any_project` | Staff user bypasses permission checks |
| 5 | `test_non_member_denied_all_operations` | 403 for create/view/edit/move/archive |

---

## Fixture Requirements

- **Users:** `group_admin` (admin role), `group_member` (member role), `outsider` (no membership), `staff_user`
- **Group:** `test_group` with active memberships for admin/member
- **Project:** Group-sponsored project with seeded columns
- **Tasks:** Multiple tasks in different columns, one archived
- **ProjectColumn:** Default 5 columns, one hidden for toggle tests

## Dependencies

- `groups.services.permissions.PermissionService` — permission checks
- `projects.permissions` — 6 permission classes (CanViewProject, CanEditProject, CanCreateTask, CanMoveTask, CanEditTask, CanArchiveTask)
- `projects.models.Task.move_task()` — reindex logic with 1M offset trick
- `projects.models.ProjectColumn.clean()` — hidden column validation

## Run Command

```bash
python manage.py test projects.tests --settings=mixtape.settings.test -v 2
```
