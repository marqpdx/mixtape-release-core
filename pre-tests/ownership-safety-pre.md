# Ownership Safety — Backend Test Plan (Pre-QA)

Date: 2026-02-11
Owner: QA / Backend
Scope: `app/groups/models/ownership.py`, `app/groups/services/ownership.py`, `app/groups/api/ownership_views.py`, `app/groups/tasks.py`, `app/groups/producers.py`

---

## 0) Preconditions / Environment

- Backend running locally with all migrations applied (through `groups.0008_ownership_change_request`).
- Celery worker running (for fanout notifications). Celery beat running (for periodic execution task).
- At least **3 user accounts**: User A (owner), User B (admin), User C (regular member).
- One Group where:
  - User A has roles `["member", "admin", "owner"]`
  - User B has roles `["member", "admin"]`
  - User C has roles `["member"]`
- Group's `ownership_change_delay_seconds` set to a short value (e.g. `60` seconds) for manual testing.

**Key endpoints:**
- `POST /api/groups/{slug}/ownership/requests/create`
- `GET /api/groups/{slug}/ownership/requests?status=PENDING`
- `POST /api/groups/{slug}/ownership/requests/{request_id}/cancel`

---

## 1) Invariant: Admin Cannot Remove/Demote Owner

**Preconditions:** User A is owner, User B is admin.

**Steps:**
1. Authenticate as User B (admin).
2. `POST /api/groups/{slug}/members/{user_a_id}/roles` with `{"role": "owner"}`.
3. Attempt to modify User A's permissions via `POST /api/groups/{slug}/members/{user_a_id}/permissions`.
4. Attempt to modify User A's roles via `POST /api/groups/{slug}/members/{user_a_id}/roles` with `{"role": "steward"}`.

**Expected:**
- Step 2: `403` — "Owner role can only be assigned via ownership change request"
- Step 3: `403` — "Cannot modify owner permissions"
- Step 4: `403` — "Cannot modify owner roles"

---

## 2) Invariant: Only Owner Can Create Ownership Request

**Preconditions:** User A is owner, User B is admin, User C is member.

**Steps:**
1. Authenticate as User B (admin).
2. `POST /api/groups/{slug}/ownership/requests/create` with `{"action": "ADD_OWNER", "target_user_id": "{user_c_id}"}`.
3. Repeat as User C (member).
4. Repeat as User A (owner).

**Expected:**
- Step 2: `403` — "Only active owners can manage ownership requests"
- Step 3: `403` — same
- Step 4: `201` — request created with `status: "PENDING"`, `execute_after` in the future

---

## 3) Invariant: Group Cannot End With Zero Owners

**Preconditions:** User A is the **sole** owner.

**Steps:**
1. Authenticate as User A.
2. `POST /api/groups/{slug}/ownership/requests/create` with `{"action": "REMOVE_OWNER", "target_user_id": "{user_a_id}"}`.
3. Wait for the request to reach `execute_after` (or manually trigger `execute_due_ownership_requests` task).

**Expected:**
- Step 2: `201` — request created (validation passes at creation since it's technically valid to request).
- Step 3: Request status becomes `"FAILED"` with `failure_reason` containing "Cannot remove the last owner".
- User A remains an owner.

---

## 4) Invariant: Owner Leaving Is Blocked (Indirect Removal)

**Context:** This tests that if a member-removal or kick/ban endpoint exists in the future, it cannot bypass ownership protections.

**Steps:**
1. Verify `GroupMembersView` is read-only (GET only, no DELETE/PATCH).
2. Verify `MemberRoleManageView` blocks role changes on owners (`403`).
3. Verify `MemberPermissionManageView` blocks permission changes on owners (`403`).
4. Verify `demote_from_owner()` in `groups/services/memberships.py` raises `NotImplementedError`.

**Expected:**
- No API path exists to remove or reduce an owner's privileges without going through the ownership change request flow.

**Note for future:** If a kick/ban/evict endpoint is added, it MUST check `membership.is_owner()` and return `403`.

---

## 5) Invariant: Pending Request Does Not Grant Privileges

**Preconditions:** User C is a regular member.

**Steps:**
1. As User A (owner): create `ADD_OWNER` request targeting User C.
2. Verify request is `PENDING`.
3. As User C: attempt to create an ownership request → `POST /api/groups/{slug}/ownership/requests/create`.
4. As User C: attempt to list ownership requests → `GET /api/groups/{slug}/ownership/requests`.
5. Check User C's roles via `GET /api/groups/{slug}/my-permissions`.

**Expected:**
- Step 3: `403` — User C is not an owner (pending doesn't count).
- Step 4: `403` — User C cannot view ownership requests.
- Step 5: roles should NOT include `"owner"`.

---

## 6) Time-Delay: Request Cannot Execute Before `execute_after`

**Preconditions:** Group's `ownership_change_delay_seconds` = `3600` (1 hour).

**Steps:**
1. As User A: create `ADD_OWNER` request for User C.
2. Note `execute_after` timestamp in response.
3. Immediately trigger `execute_due_ownership_requests` task (via Django shell or Celery).
4. Check request status.

**Expected:**
- Step 4: Request is still `PENDING` — the task skips requests where `now < execute_after`.

---

## 7) Cancel Works Immediately

**Steps:**
1. As User A: create `ADD_OWNER` request for User C. Note the `request_id`.
2. As User A: `POST /api/groups/{slug}/ownership/requests/{request_id}/cancel`.
3. Check request status via list endpoint.

**Expected:**
- Step 2: `200` — request returned with `status: "CANCELED"`, `canceled_by_id` = User A, `canceled_at` set.
- Step 3: Request shows as `CANCELED` in the list.

---

## 8) Cancel Prevents Execution

**Preconditions:** Group's `ownership_change_delay_seconds` = `5` (short delay for testing).

**Steps:**
1. As User A: create `ADD_OWNER` request for User C.
2. As User A: immediately cancel the request.
3. Wait for `execute_after` to pass.
4. Trigger `execute_due_ownership_requests` task.
5. Check request status and User C's roles.

**Expected:**
- Request remains `CANCELED` (task ignores non-PENDING requests).
- User C does NOT have owner role.

---

## 9) Execution Re-checks Invariants at Runtime

**Steps (scenario: target user leaves group between request and execution):**
1. As User A: create `ADD_OWNER` request for User C.
2. Before execution: deactivate User C's membership (set `is_active=False` via Django shell).
3. Wait for `execute_after` to pass, trigger task.

**Expected:**
- Request status becomes `"FAILED"` with `failure_reason` containing "Target user is no longer a member".
- No role changes occur.

**Steps (scenario: duplicate owner):**
1. As User A: create `ADD_OWNER` request for User B.
2. Before execution: manually grant User B the owner role via Django shell.
3. Wait for `execute_after` to pass, trigger task.

**Expected:**
- Request status becomes `"FAILED"` with `failure_reason` containing "already an owner".

---

## 10) Escrow Owner Must Also Be an Owner

**Context:** This is a design constraint verified by code inspection + data state.

**Steps:**
1. When a group is created, check that `escrow_owner` is set to the creator.
2. Verify creator has `"owner"` in their membership roles.
3. As User A: create `SET_ESCROW_OWNER` request targeting User C (a non-owner member).
4. Wait for execution.

**Expected:**
- Step 1-2: Creator is both `escrow_owner` and has owner role (verified in `GroupService.create_group`).
- Step 4: Request `EXECUTED` — `group.escrow_owner` is now User C, AND User C is auto-granted `"owner"` + `"admin"` roles.
- Verify User C's membership roles now include `"owner"`.
- `SET_ESCROW_OWNER` targeting a non-member returns `400` — "Target user must be a member of this group".

---

## 11) Changing Escrow Owner Requires Delayed Request

**Steps:**
1. Verify there is no direct API or service call to set `group.escrow_owner` without going through `OwnershipChangeRequest`.
2. As User A: `POST /api/groups/{slug}/ownership/requests/create` with `{"action": "SET_ESCROW_OWNER", "target_user_id": "{user_c_id}"}`.
3. Verify request is `PENDING` with delay.

**Expected:**
- Step 1: Only path is via `create_ownership_request()` → `execute_ownership_request()`.
- Step 2: `201` with `execute_after` in the future.
- The escrow owner is NOT changed until the request executes.

---

## 12) Duplicate Request Prevention

**Steps:**
1. As User A: create `ADD_OWNER` request for User C.
2. As User A: attempt to create another `ADD_OWNER` request for User C.

**Expected:**
- Step 2: `400` — "A pending ADD_OWNER request for this user already exists".

---

## 13) Activity Notifications

**Preconditions:** Celery worker running for fanout.

**Steps:**
1. Create an ownership request → check that `Action` exists with `activity_code = "group.ownership.requested"`.
2. Cancel the request → check for `activity_code = "group.ownership.canceled"`.
3. Create a new request and let it execute → check for `activity_code = "group.ownership.executed"`.
4. Create a request that will fail (e.g., remove last owner) → check for `activity_code = "group.ownership.failed"`.

**Expected:**
- `Action` + `ActionOutbox` created for each event.
- `Notification` created for all active group owners.
- All notifications have `channel = "system"`, `priority = "critical"`.

---

## 14) All Five Action Types Execute Correctly

Run each action type end-to-end (create → wait → execute → verify):

| Action | Setup | Expected Result |
|---|---|---|
| `ADD_OWNER` | Target is admin (User B) | User B gains `"owner"` + `"admin"` roles |
| `REMOVE_OWNER` | Target is owner (User B, after ADD) | User B loses `"owner"`, keeps `"admin"` + `"member"` |
| `DEMOTE_OWNER` | Target is owner (User B, re-added) | User B loses `"owner"` + `"admin"`, keeps `"member"` |
| `TRANSFER_OWNERSHIP` | User A transfers to User C | User C gains `"owner"` + `"admin"`, User A loses `"owner"` |
| `SET_ESCROW_OWNER` | Target is User C (member) | `group.escrow_owner` updated to User C, User C auto-granted `"owner"` + `"admin"` roles |

**Important:** For `TRANSFER_OWNERSHIP`, verify that at no point during execution does the group have zero owners (target gets owner BEFORE requester loses it).

---

## Edge Cases / Regression

- Unauthenticated user → `401` on all ownership endpoints.
- Invalid `target_user_id` (nonexistent UUID) → `404`.
- Invalid `action` string → `400`.
- Request on nonexistent group slug → `404`.
- Cancel an already-canceled request → `400`.
- Cancel an already-executed request → `400`.
