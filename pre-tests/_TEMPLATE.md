# [Feature Name] — Backend Pre-Test

**Feature:** [Short feature description]
**Date:** [YYYY-MM-DD]
**Module:** `[django_app/]`
**Test file:** `[app]/tests/test_[feature].py`
**Frontend test plan:** `mixtape-release-frontend/pre-tests/[feature]-frontend-pre.md` _(if exists)_

---

## What was built

### Models
- `ModelName` — [one-line description]

### Endpoints
- `GET /api/[path]` — [description]
- `POST /api/[path]` — [description]
- `PATCH /api/[path]/{id}` — [description]
- `DELETE /api/[path]/{id}` — [description]

### Permissions
- `[PermissionHelper]` — [what it enforces]

---

## Preconditions (setUp)

- Create users: `author`, `member_user`, `outsider`.
- Create a `[ParentModel]` owned by `author`.
- Add `member_user` as [role/collaborator].
- (Note any required mock patches or fixtures.)

---

## A) [Happy Path Group Name]

| # | Test | Assert |
|---|------|--------|
| 1 | `test_[action]_as_author` | `201`, correct fields returned |
| 2 | `test_[action]_as_member` | `201`, member can [action] |
| 3 | `test_[action]_as_outsider` | `403` |
| 4 | `test_[action]_unauthenticated` | `401` |

---

## B) [Validation Group Name]

| # | Test | Assert |
|---|------|--------|
| 1 | `test_[action]_missing_required_field` | `400`, field error in response |
| 2 | `test_[action]_with_invalid_value` | `400`, descriptive error |
| 3 | `test_[action]_duplicate` | `400` or `409` as appropriate |

---

## C) [Permissions / Access Control]

| # | Test | Assert |
|---|------|--------|
| 1 | `test_[action]_own_record` | `200/204` |
| 2 | `test_[action]_others_record` | `403` |
| 3 | `test_[action]_after_member_removed` | `403` |

---

## D) [Edge Cases]

| # | Test | Assert |
|---|------|--------|
| 1 | `test_[action]_empty_results` | `200`, empty list / empty state |
| 2 | `test_[action]_nonexistent_parent` | `404` |

---

## Deliverables
- Example success response JSON from primary endpoint.
- Permission denial response snippet (`403`).
- Validation error snippet (`400`).

---

## Notes
- All negative access checks should return `404` (not `403`) where information leakage is a concern.
- Follow the test class structure in existing tests (e.g., `class TestFeatureCreate(APITestCase): ...`).
