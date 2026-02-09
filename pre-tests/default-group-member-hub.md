# Pre-Test Plan: Default Group + Member Hub

## Scope
- Validate the default group endpoint returns settings-based group metadata.
- Validate the member hub header uses member identity, not default-group name.

## Preconditions
- Server running with `MIXTAPE_DEFAULT_GROUP_NAME`, `MIXTAPE_DEFAULT_GROUP_SLUG` configured.
- Default group exists (bootstrap or manual).
- Test user exists and can authenticate.

## Test Data
- Default group slug (from settings, default `crossroads`).
- Test user `username`.

## API Tests
1. **GET default group**
   - Request: `GET /api/groups/default`
   - Expect:
     - `200`
     - JSON contains: `id`, `slug`, `title`, `group_type`
     - `slug` matches `MIXTAPE_DEFAULT_GROUP_SLUG`
2. **Default group not found**
   - Temporarily remove/rename default group.
   - Request: `GET /api/groups/default`
   - Expect:
     - `404`
     - JSON: `{ "detail": "Default group not found." }`

## UI Tests (Member Hub)
1. **Member hub header title**
   - Navigate to `/app/member/<username>`
   - Expect: header title equals `display_name` or `username`
   - Must **not** show `My <default group name>`
2. **Header subtitle**
   - Expect subtitle `@<username>`
3. **Banner & avatar**
   - If `background_image_url` or `profile_image_url` set, they display.
   - Otherwise fallback avatar initial appears.

## Regression Checks
- Existing group pages still render.
- No impact on `/api/groups/<slug>` or `/api/groups/my`.

## Notes / Edge Cases
- If `display_name` empty, header should fall back to `username` or `Member`.
- Anonymous access to `/api/groups/default` should still work (AllowAny).
