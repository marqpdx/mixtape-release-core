# Frontend Test Agent Seed (Playwright)

## Purpose
Create a dedicated frontend QA/testing agent that owns browser-level test coverage for Mixtape UI flows, while backend agents continue owning Django/API tests.

## Initial scope (phase 1)
1. `pre-tests/dispatch-outline-phase1-frontend-pre.md`
2. `pre-tests/dispatch-comments-pre.md` (frontend behaviors only; backend contract is separate)

## Responsibilities
- Translate pre-test markdown into runnable Playwright specs.
- Keep selectors stable and intentional (prefer `data-testid` or accessible roles/names).
- Produce reproducible artifacts on failure (trace, video, screenshot, console logs).
- Report failures by bucket: UI bug, API bug, test harness issue.

## Non-goals
- No backend data-model assertions.
- No schema/migration validation.
- No replacing backend integration tests.

## Tech baseline
- Framework: Playwright (`@playwright/test`)
- Language: TypeScript
- Browser matrix: Chromium first; optional Firefox/WebKit once stable

## Proposed repo layout (frontend repo)
- `tests/e2e/dispatch/outline.spec.ts`
- `tests/e2e/dispatch/comments.spec.ts`
- `tests/e2e/_helpers/auth.ts`
- `tests/e2e/_helpers/fixtures.ts`
- `playwright.config.ts`

## Environment contract
- Frontend app URL from env: `E2E_BASE_URL`
- Test user creds from env:
  - `E2E_AUTHOR_EMAIL`, `E2E_AUTHOR_PASSWORD`
  - `E2E_EDITOR_EMAIL`, `E2E_EDITOR_PASSWORD`
  - `E2E_COMMENTER_EMAIL`, `E2E_COMMENTER_PASSWORD`
  - `E2E_OUTSIDER_EMAIL`, `E2E_OUTSIDER_PASSWORD`
- Test backend should already be seeded/reset by backend test harness.

## Execution contract
- Local run:
  - `npx playwright test tests/e2e/dispatch/outline.spec.ts`
  - `npx playwright test tests/e2e/dispatch/comments.spec.ts`
- CI run:
  - block merge on any failed critical scenario
  - attach trace/video/screenshot artifacts

## Mapping: Dispatch Outline pre-test -> Playwright suites
Use `pre-tests/dispatch-outline-phase1-frontend-pre.md` as source of truth for:
- heading extraction
- tree nesting
- click-to-scroll navigation
- active heading highlight
- toolbar H1/H2/H3 behavior
- drawer UX and edge cases

## Mapping: Dispatch Comments pre-test -> Playwright suites
Use frontend-facing scenarios from `pre-tests/dispatch-comments-pre.md` for:
- comment composer visibility and permissions
- inline anchoring/highlight rendering
- thread/reply display
- resolve/unresolve UX
- edit/delete affordances by role

Note: backend API semantics (status codes, payload shape) are validated by Django tests and should be treated as external contract by Playwright tests.

## Test design rules
- Prefer role-based locators first (`getByRole`), then `data-testid`.
- Never use brittle CSS-only selectors for primary interactions.
- Keep each scenario independent (no shared mutable UI state).
- Use helper to seed or create a fresh dispatch piece per test when possible.
- Assert user-visible outcomes first, network calls second.

## Failure triage format
For every failing test, output:
1. Scenario name
2. Last successful step
3. Actual vs expected
4. Artifact links (trace/video/screenshot)
5. Suspected owner: frontend / backend / infra

## Hand-off checklist for the frontend test team
- Confirm selector strategy (`data-testid` additions where needed).
- Implement `outline.spec.ts` first from existing pre-test.
- Implement `comments.spec.ts` after backend comments API contract is available.
- Add a smoke subset tag for fast PR gating.
- Document command to run only dispatch frontend tests.
