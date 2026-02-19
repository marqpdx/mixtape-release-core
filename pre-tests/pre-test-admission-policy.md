# Pre-Test Plan: Group Admission Policy

**Feature:** 6-Level Admission Control + Join/Request Flow
**Date:** 2026-02-19
**Modules:** `groups/`, `public_api/`
**Test files:** `groups/tests/test_join_service.py`, `groups/tests/test_join_api.py`, `public_api/tests/test_admission_status.py`

---

## What was built

### Backend
- Expanded `AdmissionPolicy` enum from 3 → 6 values on base `Group` model
- `join_service.py`: `join_group()`, `request_to_join_group()`, `respond_to_join_request()`, `get_admission_status()`
- Public endpoint: `GET /api/public/groups/{slug}/admission-status`
- Authenticated endpoints: `POST /api/groups/{slug}/join`, `POST /api/groups/{slug}/request-join`
- Admin endpoints: `GET /api/groups/{slug}/join-requests`, `POST /api/groups/{slug}/join-requests/{id}/respond`
- Activity producers: `on_member_joined`, `on_join_request_submitted`, `on_join_request_responded`
- Email notification to moderators on join request

### Frontend
- Admission status CTA on group public page (ViewerStrip)
- Admin join-requests page, admin settings page (admission policy picker)

---

## Test Suite Plan

### A. join_service — `join_group()` Tests

| # | Test | Assert |
|---|------|--------|
| 1 | `test_join_open_group` | User joins, membership created with role=member, 200 |
| 2 | `test_join_open_parent_members_as_parent_member` | Parent member joins child group, membership created |
| 3 | `test_join_open_parent_members_not_parent_member` | ValidationError raised |
| 4 | `test_join_open_parent_members_no_parent` | ValidationError (group has no parent) |
| 5 | `test_join_application_policy_rejects_direct_join` | ValidationError (policy doesn't allow direct join) |
| 6 | `test_join_invite_only_rejects` | ValidationError |
| 7 | `test_join_closed_rejects` | ValidationError |
| 8 | `test_join_already_member` | ValidationError ("already a member") |
| 9 | `test_join_fires_on_member_joined` | Activity producer called (mock check) |

### B. join_service — `request_to_join_group()` Tests

| # | Test | Assert |
|---|------|--------|
| 1 | `test_request_application_policy` | GroupInvitation created with kind=REQUEST, status=PENDING |
| 2 | `test_request_application_parent_members_as_parent_member` | Invitation created |
| 3 | `test_request_application_parent_members_not_parent_member` | ValidationError |
| 4 | `test_request_open_policy_rejects` | ValidationError (open doesn't accept requests) |
| 5 | `test_request_duplicate_pending` | ValidationError ("already have a pending request") |
| 6 | `test_request_already_member` | ValidationError |
| 7 | `test_request_with_message` | Invitation.message saved correctly |
| 8 | `test_request_fires_on_join_request_submitted` | Activity producer called |
| 9 | `test_request_sends_email_to_moderators` | `send_transactional_email_task.delay` called with correct recipients |

### C. join_service — `respond_to_join_request()` Tests

| # | Test | Assert |
|---|------|--------|
| 1 | `test_accept_creates_membership` | Invitation status=JOINED, membership created |
| 2 | `test_decline_sets_declined` | Invitation status=DECLINED, no membership |
| 3 | `test_respond_invalid_action` | ValidationError |
| 4 | `test_respond_already_processed` | ValidationError (not pending) |
| 5 | `test_respond_non_request_invitation` | ValidationError (kind != REQUEST) |
| 6 | `test_accept_fires_on_join_request_responded` | Activity producer called with action="accept" |
| 7 | `test_decline_fires_on_join_request_responded` | Activity producer called with action="decline" |

### D. join_service — `get_admission_status()` Tests

| # | Test | Assert |
|---|------|--------|
| 1 | `test_status_anonymous_open` | can_join=True, is_member=False |
| 2 | `test_status_anonymous_application` | can_request=True |
| 3 | `test_status_anonymous_closed` | can_join=False, can_request=False |
| 4 | `test_status_member` | is_member=True, can_join=False |
| 5 | `test_status_moderator` | is_member=True, is_moderator=True |
| 6 | `test_status_pending_request` | has_pending_request=True, can_request=False |
| 7 | `test_status_open_parent_members_is_parent_member` | can_join=True |
| 8 | `test_status_open_parent_members_not_parent_member` | can_join=False |
| 9 | `test_status_parent_group_info` | parent_group dict with title/slug |
| 10 | `test_status_requires_parent_membership_flag` | requires_parent_membership=True for parent policies |

### E. API — Public Admission Status Endpoint

| # | Test | Assert |
|---|------|--------|
| 1 | `test_admission_status_anonymous` | 200, returns policy and can_join/can_request |
| 2 | `test_admission_status_authenticated_member` | 200, is_member=True |
| 3 | `test_admission_status_nonexistent_group` | 404 |
| 4 | `test_admission_status_inactive_group` | 404 |
| 5 | `test_group_detail_includes_admission_policy` | PublicGroupDetail response has admission_policy field |

### F. API — Join and Request Endpoints

| # | Test | Assert |
|---|------|--------|
| 1 | `test_join_endpoint_success` | POST /join → 200, "joined" |
| 2 | `test_join_endpoint_unauthenticated` | 401 |
| 3 | `test_join_endpoint_wrong_policy` | 400, validation error |
| 4 | `test_request_join_endpoint_success` | POST /request-join → 201, invitation_id returned |
| 5 | `test_request_join_endpoint_with_message` | Message saved on invitation |
| 6 | `test_request_join_endpoint_unauthenticated` | 401 |

### G. API — Admin Join Request Management

| # | Test | Assert |
|---|------|--------|
| 1 | `test_list_join_requests_as_admin` | 200, returns pending requests |
| 2 | `test_list_join_requests_as_non_admin` | 403 |
| 3 | `test_list_join_requests_unauthenticated` | 401 |
| 4 | `test_respond_accept` | POST /respond with action=accept → 200 |
| 5 | `test_respond_decline` | POST /respond with action=decline → 200 |
| 6 | `test_respond_invalid_action` | 400 |
| 7 | `test_respond_as_non_admin` | 403 |

### H. Migration

| # | Test | Assert |
|---|------|--------|
| 1 | `test_migration_0009_applies` | `python manage.py migrate` succeeds |
| 2 | `test_group_has_admission_policy_field` | Group model has admission_policy with default="open" |

---

## Fixture Requirements

- **Users:** `owner_user` (group owner), `admin_user` (group admin), `member_user`, `outsider_user`, `parent_member_user`
- **Groups:** `community_group` (parent, open), `circle_group` (child, sponsored by community_group)
- **Memberships:** Owner/admin/member in community_group; parent_member in community_group only
- **GroupInvitation:** Pending REQUEST for duplicate-check tests
- **AdmissionPolicy variations:** Test with each of 6 policies

## Dependencies

- `groups.services.memberships.ensure_user_membership` — existing
- `groups.models.GroupInvitation` with InvitationKind.REQUEST — existing
- `groups.producers` — mock for activity tests
- `utils.tasks.send_transactional_email_task` — mock for email tests
- `groups.services.permissions.PermissionService` — for admin checks

## Run Command

```bash
python manage.py test groups.tests.test_join_service groups.tests.test_join_api public_api.tests.test_admission_status --settings=mixtape.settings.test -v 2
```
