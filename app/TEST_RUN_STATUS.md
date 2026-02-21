# Latest Test Run Status

Update this file only for test areas that were run.

| Test area | Last run (UTC) | Status | Notes |
|---|---|---|---|
| `dispatch.tests` | 2026-02-19 22:20:31 UTC | PASS | `app/run_tests_quiet.sh dispatch.tests` |
| `groups.tests.test_join_service` | 2026-02-19 22:20:31 UTC | PASS | `app/run_tests_quiet.sh groups.tests.test_join_service` |
| `groups.tests.test_join_api` | 2026-02-19 22:20:31 UTC | PASS | `app/run_tests_quiet.sh groups.tests.test_join_api` |
| `public_api.tests` | 2026-02-19 22:20:31 UTC | PASS | `app/run_tests_quiet.sh public_api.tests` |
| `projects.tests` | 2026-02-21 04:59:35 UTC | PASS | `app/run_tests_quiet.sh projects.tests` (includes non-mocked regression checks for issues #1 and #2). |
| `groups.tests.test_join_api_integration` | 2026-02-21 04:59:35 UTC | PASS | `app/run_tests_quiet.sh groups.tests.test_join_api_integration` (non-mocked regression checks for issue #3). |
| `dispatch.test_comments` | 2026-02-21 04:05:06 UTC | FAIL | `app/run_tests_quiet.sh dispatch.test_comments` -> all comment endpoint routes currently return `404` (not implemented/wired yet). |
| `writing.tests` | 2026-02-21 04:17:48 UTC | PASS | `app/run_tests_quiet.sh writing.tests` (includes new Voice Seeds v1 backend tests). |
