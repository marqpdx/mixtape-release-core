# Projects — Security & Quality Fixes Pre-Test Handoff

**Scope**
Validate the security and quality fixes made during the projects puddlejump pass (2026-03-11). Two code changes:
- **S1**: `ProjectPermissionBase` now raises `Http404` instead of returning `False` — unauthorized access to any project/task endpoint returns 404 (not 403).
- **Q1**: `Task.create_in_column` is now wrapped in `transaction.atomic()` with `select_for_update()` on position read — prevents race condition on concurrent task creation.

**Key Principles**
- Authenticated users accessing another user's or group's project/task get **404** (not 403).
- Unauthenticated users get **401**.
- Concurrent task creation in the same column must not produce a database constraint error.

---

## Preconditions

- Local dev env running.
- Two test users: `user_a` (member of a Group with a Project) and `user_b` (no access to that Group).
- A Project created by `user_a` in their Group. Note the `id` as `<PROJECT_ID>`.
- At least one Task in that Project. Note its `id` as `<TASK_ID>`.
- Get project data via:
  ```
  GET /api/projects/projects/list?sponsor_type=group&sponsor_object_id=<GROUP_ID>
  Authorization: Bearer <USER_A_TOKEN>
  ```

---

## Section A — Access Control (S1)

### A1) Board — own group's project

**Request**
```
GET /api/projects/projects/<PROJECT_ID>/board
Authorization: Bearer <USER_A_TOKEN>
```

**Expected**
- 200 OK
- `{ "project": {...}, "columns": [...], "tasks_by_column": {...} }`

**Verify**
- [ ] Response includes all 5 default columns
- [ ] Tasks are grouped by column id

---

### A2) Board — another user's project

**Request**
```
GET /api/projects/projects/<PROJECT_ID>/board
Authorization: Bearer <USER_B_TOKEN>
```

**Expected**
- 404 Not Found

**Verify**
- [ ] Response is 404, not 403
- [ ] User B cannot infer that the project exists

---

### A3) Board — unauthenticated

**Request**
```
GET /api/projects/projects/<PROJECT_ID>/board
(no Authorization header)
```

**Expected**
- 401 Unauthorized

---

### A4) Create task — unauthorized project

**Request**
```
POST /api/projects/projects/<PROJECT_ID>/tasks
Authorization: Bearer <USER_B_TOKEN>
Content-Type: application/json

{"title": "Sneaky task"}
```

**Expected**
- 404 Not Found

---

### A5) Move task — unauthorized

**Request**
```
POST /api/projects/tasks/<TASK_ID>/move
Authorization: Bearer <USER_B_TOKEN>
Content-Type: application/json

{"to_column_id": "<ANY_COLUMN_ID>", "to_index": 0}
```

**Expected**
- 404 Not Found

---

### A6) Update task — unauthorized

**Request**
```
PATCH /api/projects/tasks/<TASK_ID>
Authorization: Bearer <USER_B_TOKEN>
Content-Type: application/json

{"title": "Hijacked"}
```

**Expected**
- 404 Not Found

---

### A7) Archive task — unauthorized

**Request**
```
POST /api/projects/tasks/<TASK_ID>/archive
Authorization: Bearer <USER_B_TOKEN>
```

**Expected**
- 404 Not Found

---

### A8) Toggle column hidden — unauthorized

**Request**
```
PATCH /api/projects/projects/<PROJECT_ID>/columns/<COLUMN_ID>/toggle-hidden
Authorization: Bearer <USER_B_TOKEN>
```

**Expected**
- 404 Not Found

---

## Section B — Task Creation Race Condition (Q1)

### B1) Sequential task creation — positions are unique

**Steps**
1. As `user_a`, create 5 tasks in the Backlog column in sequence
2. Fetch board

**Expected**
- All 5 tasks present with unique `position` values (0, 1, 2, 3, 4)
- No database constraint error

**Verify**
- [ ] `position` values are contiguous and unique per column

---

### B2) Concurrent task creation — no constraint violation

> **Note:** This test requires tooling to send concurrent requests (e.g., `ab`, `locust`, or two parallel curl calls).

**Steps**
1. Send 5 simultaneous `POST /api/projects/projects/<PROJECT_ID>/tasks` requests as `user_a` to the same column

**Expected**
- All 5 tasks created (200 or 201 for each)
- No 500 errors
- Board fetch shows all 5 tasks with unique positions

**Verify**
- [ ] No HTTP 500 responses
- [ ] No `UniqueConstraint` database errors in server logs
- [ ] All tasks appear in board with distinct positions

---

## Section C — Existing Endpoints Regression

- [ ] `POST /api/projects/projects` still creates a project and seeds 5 columns
- [ ] `GET /api/projects/projects/list?sponsor_type=group&sponsor_object_id=<GROUP_ID>` still returns project list
- [ ] `POST /api/projects/tasks/<TASK_ID>/move` still moves tasks correctly (column + position update)
- [ ] Moving into `done` column sets `completed_at`; moving out clears it
- [ ] `PATCH /api/projects/tasks/<TASK_ID>` still updates title/summary
- [ ] `POST /api/projects/tasks/<TASK_ID>/archive` still removes task from board
- [ ] `PATCH /api/projects/projects/<PROJECT_ID>/columns/<COLUMN_ID>/toggle-hidden` still returns 400 when column has tasks

---

## Notes

- The 404 behavior (S1) applies to all authenticated-but-unauthorized access. Admin/staff users bypass this check and retain full access.
- For B2 (concurrent creation), constraint violations before this fix would manifest as HTTP 500 with a `django.db.utils.IntegrityError` in logs. After fix, all requests should succeed.
- Column hiding rules (cannot hide a column with tasks) are enforced at the model level via `clean()` — unchanged by this pass.
