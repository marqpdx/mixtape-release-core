# Activity Subsystem — Backend Test Plan (Pre‑QA)

Date: 2026-01-28
Owner: QA / Backend
Scope: `app/activity/**` API + fanout + preferences

---

## 0) Preconditions / Environment

- Backend running locally with migrations applied (including `activity.0003_notification_level`).
- A valid user account with auth cookies or token.
- At least two users to test audience resolution and actor exclusion.
- Celery worker running (fanout). If not, fanout will not create Notifications.

**Optional fixtures**:
- One Group with 2+ members
- One WritingPiece (group-sponsored) and a WritingComment

---

## 1) Activity Fanout Pipeline (Action → Notification)

### 1.1 Chat mention (canonical path)
**Preconditions:** Two users (A and B), a chat conversation between them, and a message that mentions B.

**Steps:**
1. User A posts a message mentioning user B.
2. Ensure producer creates `Action` + `ActionOutbox` (DB check).
3. Verify Celery fanout runs.

**Expected:**
- `Action` row exists with `activity_code=chat.mention`.
- `ActionOutbox` exists and has `dispatched_at` set.
- `Notification` exists for user B, not for user A.
- `Notification.level` is set (realtime by default).

**Failure modes:**
- No notification created (likely fanout not triggered).
- Duplicate notifications (double dispatch).

### 1.2 Dedupe key uniqueness
**Steps:**
1. Trigger two distinct actions with different activity codes on different objects.
2. Compare `Action.dedupe_key` values.

**Expected:**
- Dedupe keys are namespaced with activity code and do not collide.

---

## 2) API — Notification List + Pagination

### 2.1 List endpoint
**Endpoint:** `GET /api/activity/`

**Steps:**
1. Call endpoint as authenticated user.
2. Verify JSON contains `results` array.
3. Confirm each item includes `level`, `priority`, `bucket`, `action_url`.

**Expected:**
- Cursor pagination response with keys: `results`, `next`, `previous`.

### 2.2 Pagination
**Steps:**
1. Request page 1 and capture `next` URL.
2. Call `next` and verify results differ.

**Expected:**
- Cursor changes and results advance.

---

## 3) API — Summary Endpoint (No N+1)

**Endpoint:** `GET /api/activity/summary`

**Steps:**
1. Call endpoint and inspect response keys.
2. Verify `notifications_unread_by_bucket` and `messages_unread_by_conversation` keys.

**Expected:**
- Counts reflect unread notifications and conversation unread counts.
- Performance: no per‑conversation N+1 query spikes (optional profiling).

---

## 4) API — Mark Read

### 4.1 Mark Read (specific IDs)
**Endpoint:** `POST /api/activity/mark-read`

**Steps:**
1. Submit notification IDs for current user.
2. Confirm response `{ updated: N }`.
3. Re-fetch list and confirm `is_read=true`.

**Expected:**
- Marked notifications show `is_read=true`, `is_seen=true`.

### 4.2 Mark All Read
**Endpoint:** `POST /api/activity/mark-all-read?bucket=activity`

**Expected:**
- All notifications in bucket marked read.

---

## 5) API — Dismiss / Delete

**Endpoint:** `DELETE /api/activity/<notification_id>`

**Steps:**
1. Delete a notification belonging to the user.
2. Attempt to delete a notification belonging to another user.

**Expected:**
- Own notification deleted (204).
- чужой notification returns 404.

---

## 6) Preferences Endpoint

### 6.1 List Preferences
**Endpoint:** `GET /api/activity/preferences`

**Expected:**
- Returns a list of preference objects (possibly empty).

### 6.2 Upsert Preference
**Endpoint:** `POST /api/activity/preferences`

**Payloads:**
- Bucket preference: `{ "bucket": "activity", "level": "digest" }`
- Activity code preference: `{ "activity_code": "chat.mention", "level": "realtime" }`

**Expected:**
- Preference is created or updated (same row updated on repeat).

---

## 7) `action_url` Resolution

**Steps:**
1. Trigger a notification for a Group object.
2. Trigger a notification for a WritingPiece.
3. Trigger a notification for a WritingComment (if available).

**Expected:**
- Group → `/app/groups/<slug>`
- WritingPiece → `/app/groups/<group_slug>/writing/<piece_slug>`
- WritingComment → writing URL + `#comment-<id>`

---

## 8) Digest Level Behavior (Current Phase 1)

**Steps:**
1. Create preference with `level=digest` for bucket.
2. Trigger a matching notification.

**Expected:**
- Notification is created immediately and visible in list (digest treated as realtime for now).

---

## 9) Edge Cases

- Invalid audience spec → producer should raise and not create Action.
- Post participants audience when post is missing → no notifications.
- Multiple actions in same aggregate → `aggregate_count` increments correctly.

