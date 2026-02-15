# Pre-Test Plan: Public API (`public_api`)

**Feature:** Member Public Face — Backend API
**Date:** 2026-02-14
**Module:** `public_api/`
**Test file:** `public_api/tests/test_public_api.py`

---

## What was built

Three new AllowAny endpoints under `/api/public/`:

1. `GET /api/public/members/{username}` — Lean public profile (no email, roles, internal fields)
2. `GET /api/public/members/{username}/shelves` — Public shelves with writing items inline
3. `GET /api/public/writing/{slug}` — Public reading endpoint for a single writing piece

---

## Test Suite Plan

### A. PublicMemberProfileView Tests

| # | Test | Assert |
|---|------|--------|
| 1 | `test_get_profile_anonymous` | 200, returns display_name, username, quick_intro, avatar_url, date_joined |
| 2 | `test_get_profile_authenticated` | 200, same shape as anonymous |
| 3 | `test_get_profile_no_email_no_roles` | Response does NOT contain `email`, `roles`, `is_active`, `first_name`, `last_name` |
| 4 | `test_get_profile_nonexistent_user` | 404 |
| 5 | `test_get_profile_inactive_user` | 404 (user.is_active=False) |
| 6 | `test_get_profile_soft_deleted` | 404 (profile.deleted_at set) |

### B. PublicMemberShelvesView Tests

| # | Test | Assert |
|---|------|--------|
| 1 | `test_shelves_anonymous_sees_public_only` | Only visibility="public" libraries returned |
| 2 | `test_shelves_authenticated_sees_public_and_members` | Both "public" and "members" libraries returned |
| 3 | `test_shelves_excludes_private_and_unlisted` | Private/unlisted libraries never returned |
| 4 | `test_shelves_only_writing_scope` | Only scope="writing" libraries returned |
| 5 | `test_shelves_items_inline` | Each shelf has `items` array with correct fields |
| 6 | `test_shelves_items_only_published_pieces` | Draft/archived pieces excluded |
| 7 | `test_shelves_items_respect_placement_visibility` | Items filtered by `can_view_placement()` |
| 8 | `test_shelves_nonexistent_user` | 404 |
| 9 | `test_shelves_empty_when_no_libraries` | 200, empty array |
| 10 | `test_shelves_item_count_matches_items` | `item_count` matches len(items) |

### C. PublicWritingPieceView Tests

| # | Test | Assert |
|---|------|--------|
| 1 | `test_get_piece_anonymous_public_placement` | 200, returns title, body_json, author info |
| 2 | `test_get_piece_no_email_in_author` | author object has username, display_name, avatar_url only |
| 3 | `test_get_piece_draft_returns_404` | Draft pieces not accessible |
| 4 | `test_get_piece_no_visible_placement_returns_404` | Published piece but no public placement → 404 |
| 5 | `test_get_piece_private_placement_anonymous` | Private placement → 404 for anonymous |
| 6 | `test_get_piece_members_placement_authenticated` | Members-only placement → 200 for authenticated |
| 7 | `test_get_piece_nonexistent_slug` | 404 |
| 8 | `test_get_piece_increments_view_count` | view_count increases by 1 |
| 9 | `test_get_piece_applies_overrides` | Placement overrides (title, excerpt) applied in response |

---

## Fixture Requirements

- **Users:** `testuser` (content author), `otheruser` (viewer), plus anonymous (no auth)
- **UserProfile:** Profile for testuser (display_name, quick_intro, avatar_url)
- **Library:** At least 3 libraries per user:
  - Public/writing scope (with placements)
  - Members/writing scope (with placements)
  - Private/writing scope (should be excluded)
- **WritingPiece:** Published piece with WritingVersion artifact
- **ContentPlacement:** Shelf placements with varying visibility (public, members, private)
- **PublicationGroup:** Required FK for ContentPlacement

## Dependencies

- `publishing.services.content_access.can_view_placement` — already tested in `publishing/tests/test_content_access.py`
- `publishing.services.content_display.get_display_payload` — already tested in `publishing/tests/test_content_display.py`
- `profiles.models.UserProfile` — existing model
- `stackroom.models.Library` — existing model
- `writing.models.WritingPiece`, `WritingVersion` — existing models

## Run Command

```bash
python manage.py test public_api.tests --settings=mixtape.settings.test -v 2
```
