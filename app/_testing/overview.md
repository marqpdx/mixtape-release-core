# Testing Strategy Overview

We are moving toward a comprehensive, repeatable testing architecture that is both strict (data integrity, contracts) and practical (fast feedback loops, low-friction local runs). The current foundation includes deterministic test data, explicit separation of app vs integration layers, and standardized tooling for reset + migration + execution.

## Current State

- Dedicated test database (`crossroads_test`) with a reset command that drops/recreates schema and requires migrations.
- Test settings isolated in `mixtape.settings.test` with `TEST_DB_*` env overrides.
- Quiet, repeatable test runner script that resets, migrates, and runs targeted suites with logs captured.
- Collection Curation API suite implemented with polymorphic `LibraryItem` coverage.

## Next Steps

- Add CI entry points that use `mixtape.settings.test` and `run_tests_quiet.sh` for smoke coverage.
- Extend app-level suites to other apps using the same patterns (serializers, models, views).
- Introduce integration test markers and a dedicated runner to target Qdrant/embedding coverage.
- Add contract tests for permissions as soon as permission classes are active.
- Track coverage and flake-prone tests; enforce determinism (no shared mutable state).

---

# Testing Standards and Guidelines

This document defines a consistent testing strategy for Mixtape apps. It is intentionally conservative and favors correctness, determinism, and traceable failures.

## Test Layers

- App-level tests: Pure Django behavior (models, serializers, views, services). Fast and deterministic; no external dependencies.
- Integration tests: Validate contracts across system boundaries (Qdrant, embeddings providers, external services). Slower and environment-dependent.

## Separation Strategy

- App-level tests live under each app’s `tests/` directory and avoid network calls or external services.
- Integration tests live under `tests/integration/` or are named `test_integration_*` within an app’s `tests/` directory.
- Integration tests can assume external services are running and correctly configured.

## Naming Conventions

- `test_<area>_api.py`: API endpoints (request/response behavior).
- `test_<area>_serializers.py`: Serializer validation and shape.
- `test_<area>_model.py`: Model constraints, ordering, defaults.
- `test_integration_<area>.py`: Cross-service contracts and end-to-end behavior.

## Fixture Guidelines

- Use explicit, minimal fixtures for each test class.
- Prefer deterministic IDs/values only when required by contract or uniqueness constraints.
- When a sponsor is required, use a real Group/User and set sponsor and submitted_by before save.
- Prefer `mixtape.services.defaults.ensure_default_group` to create a default Group when shared setup is needed.

## Assertions

- Assert both HTTP status and response schema for API tests.
- Check counts/relations for integrity (e.g., item_count, file_count, unique constraints).
- Verify negative cases for auth, permissions, and invalid input.

## Auth and Permissions

- For authenticated endpoints, include a dedicated unauthenticated test.
- When permissions are not implemented, still include test placeholders that describe expected behavior.

## External Services

- Integration tests may call Qdrant, embedding providers, or other services.
- Failures due to missing services are acceptable in local-only runs; document prerequisites in the test module.

## Data Integrity

- Tests should verify invariants such as idempotency, uniqueness, and “no side-effects” rules.
- For delete operations, ensure only the intended records are removed.

## Cleanliness

- Tests must not rely on execution order.
- Avoid shared mutable globals; use class-level setup only for truly immutable fixtures.
