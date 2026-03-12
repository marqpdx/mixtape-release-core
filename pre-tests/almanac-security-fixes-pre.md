# Almanac — Security & Quality Fixes Pre-Test Handoff

**Scope**
Validate the security and quality fixes made during the almanac puddlejump pass (2026-03-12). Six code changes across backend and frontend:
- **B1**: Site-wide action views now look up events by `id` (UUID) instead of crashing with KeyError on missing `event_slug` kwarg.
- **B2**: Occurrence URL patterns changed from `<int:occurrence_id>` to `<uuid:occurrence_id>` — occurrence endpoints now routable.
- **B3**: Dead first `EventAttendeesView` definition (used wrong kwarg) removed.
- **SEC-6**: `str(e)` removed from `EventSyncRsvpsView`, `GroupEventSyncRsvpsView`, `BulkRSVPView` error responses.
- **QC-4**: Debug `print()` statements removed from `EventListCreateMixin` and `GroupEventListCreateView`.
- **F1/F2**: Frontend `cancelRsvp()` URL and method corrected; `listEvents()` site-wide URL corrected.

**Key Principles**
- Site-wide event action endpoints (`/api/almanac/events/<id>/publish` etc.) must work by UUID, not slug.
- Occurrence endpoints (`/api/almanac/occurrences/<uuid>/rsvp` etc.) must match and route correctly.
- Error responses must not expose internal exception details.
- No debug output in server logs during normal operation.

---

## Preconditions

- Local dev env running.
- Test user `user_a` with a group and at least one published event in that group.
- Note the event's `id` (UUID) as `<EVENT_ID>` and `slug` as `<EVENT_SLUG>`.
- Note a future occurrence `id` (UUID) as `<OCCURRENCE_ID>`.
- Get event data via:
  ```
  GET /api/groups/<GROUP_SLUG>/almanac/
  Authorization: Bearer <USER_A_TOKEN>
  ```

---

## Section A — Site-wide Action Endpoints (B1)

### A1) Publish via site-wide UUID endpoint

**Request**
```
POST /api/almanac/events/<EVENT_ID>/publish
Authorization: Bearer <USER_A_TOKEN>
```

**Expected**
- 200 OK (or 400 if already published)
- Response includes `"status": "published"`

**Verify**
- [ ] Response is 200 (or 400 with `"Only draft events can be published"`)
- [ ] No 500 error in server logs

---

### A2) Unpublish via site-wide UUID endpoint

**Request**
```
POST /api/almanac/events/<EVENT_ID>/unpublish
Authorization: Bearer <USER_A_TOKEN>
```

**Expected**
- 200 OK
- Response includes `"status": "draft"`

**Verify**
- [ ] Response is 200
- [ ] No KeyError in server logs

---

### A3) RSVP via site-wide UUID endpoint

**Request**
```
POST /api/almanac/events/<EVENT_ID>/rsvp
Authorization: Bearer <USER_A_TOKEN>
Content-Type: application/json

{"status": "going"}
```

**Expected**
- 201 Created
- Response includes `attendees_created` count

**Verify**
- [ ] Response is 201
- [ ] No 500 error

---

### A4) Follow via site-wide UUID endpoint

**Request**
```
POST /api/almanac/events/<EVENT_ID>/follow
Authorization: Bearer <USER_A_TOKEN>
Content-Type: application/json

{"follow_type": "following"}
```

**Expected**
- 201 Created or 200 OK (if already following)

**Verify**
- [ ] Response is 201 or 200
- [ ] No KeyError in server logs

---

### A5) Analytics via site-wide UUID endpoint

**Request**
```
GET /api/almanac/events/<EVENT_ID>/analytics
Authorization: Bearer <USER_A_TOKEN>
```

**Expected**
- 200 OK
- Response includes `total_occurrences`, `total_rsvps`, `occurrence_stats`

**Verify**
- [ ] Response is 200
- [ ] `event_id` in response matches `<EVENT_ID>`

---

## Section B — Occurrence Endpoints (B2)

### B1) RSVP to specific occurrence

**Request**
```
POST /api/almanac/occurrences/<OCCURRENCE_ID>/rsvp
Authorization: Bearer <USER_A_TOKEN>
Content-Type: application/json

{"status": "going"}
```

**Expected**
- 201 Created
- Response includes attendee record

**Verify**
- [ ] Response is 201 (not 404)
- [ ] No URL pattern mismatch error

---

### B2) Cancel RSVP to specific occurrence

**Request**
```
POST /api/almanac/occurrences/<OCCURRENCE_ID>/cancel-rsvp
Authorization: Bearer <USER_A_TOKEN>
```

**Expected**
- 200 OK
- Response: `{"status": "RSVP cancelled"}`

**Verify**
- [ ] Response is 200 (not 404 or 405)
- [ ] Uses POST method (not DELETE)

---

### B3) Get occurrence detail

**Request**
```
GET /api/almanac/occurrences/<OCCURRENCE_ID>
Authorization: Bearer <USER_A_TOKEN>
```

**Expected**
- 200 OK
- Occurrence object

**Verify**
- [ ] Response is 200 (not 404)

---

## Section C — Error Response Security (SEC-6)

### C1) Sync RSVPs — verify no exception leak

**Steps**
1. POST to `/api/almanac/events/<EVENT_ID>/sync-rsvps` as `user_a`
2. If sync succeeds, check response is `{"status": "RSVPs synced successfully"}`
3. To test error path: temporarily break the sync (or use a deleted event ID) and confirm error response is `{"error": "Sync failed"}` — no stack trace or exception text

**Verify**
- [ ] Success response: `{"status": "RSVPs synced successfully"}`
- [ ] Error response (if triggered): `{"error": "Sync failed"}` — no `str(e)` in body

---

## Section D — No Debug Output (QC-4)

### D1) Create event — no debug print in logs

**Steps**
1. POST to `/api/groups/<GROUP_SLUG>/almanac/` to create a new event
2. Check server stdout/logs

**Expected**
- No `DEBUG: perform_create()` lines
- No `DEBUG: get_sponsor()` lines
- No `DEBUG: self.kwargs = ...` lines

**Verify**
- [ ] Server logs contain no DEBUG prints from almanac views

---

## Section E — Regression

- [ ] `GET /api/groups/<GROUP_SLUG>/almanac/` still lists group events
- [ ] `POST /api/groups/<GROUP_SLUG>/almanac/` still creates event and seeds occurrences
- [ ] `GET /api/groups/<GROUP_SLUG>/almanac/<EVENT_SLUG>` still returns event detail
- [ ] `POST /api/groups/<GROUP_SLUG>/almanac/<EVENT_SLUG>/publish` still publishes
- [ ] `GET /api/groups/<GROUP_SLUG>/almanac/calendar?start=...&end=...` still returns calendar data
- [ ] `GET /api/almanac/calendar?start=...&end=...` still returns site-wide calendar data
- [ ] `GET /api/almanac/decorators` still lists decorators

---

## Notes

- B1 fix: The six site-wide views (`EventPublishView`, `EventUnpublishView`, `EventRSVPView`, `EventFollowView`, `EventSyncRsvpsView`, `EventAnalyticsView`) were previously completely broken due to a `KeyError` on `kwargs['event_slug']` — they had never worked since the URL pattern was changed to use `event_id`. After fix they work by UUID.
- B2 fix: Occurrence endpoints require UUID in URL path. Django's `<int:>` pattern never matched UUID strings, so these routes simply returned 404 for any valid occurrence ID. After fix they route correctly.
- SEC-6: Error responses from sync and bulk-RSVP views previously included `str(e)` which could expose internal exception messages (including DB errors, tracebacks, internal model details). After fix they return a generic message only.
- F1 frontend fix: `cancelRsvp()` previously called DELETE with underscore URL — both wrong. The URL pattern is `cancel-rsvp` (hyphen) and the view handles POST.
