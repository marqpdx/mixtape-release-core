# Latest Test Run Status

Update this file only for test areas that were run.

| Test area | Last run (UTC) | Status | Notes |
|---|---|---|---|
| `dispatch.tests` | 2026-02-19 22:20:31 UTC | PASS | `app/run_tests_quiet.sh dispatch.tests` |
| `groups.tests.test_join_service` | 2026-02-19 22:20:31 UTC | PASS | `app/run_tests_quiet.sh groups.tests.test_join_service` |
| `groups.tests.test_join_api` | 2026-02-19 22:20:31 UTC | PASS | `app/run_tests_quiet.sh groups.tests.test_join_api` |
| `public_api.tests` | 2026-02-19 22:20:31 UTC | PASS | `app/run_tests_quiet.sh public_api.tests` |
| `groups.tests.test_join_api_integration` | 2026-02-21 04:59:35 UTC | PASS | `app/run_tests_quiet.sh groups.tests.test_join_api_integration` (non-mocked regression checks for issue #3). |
| `dispatch.test_comments` | 2026-02-21 04:05:06 UTC | FAIL | `app/run_tests_quiet.sh dispatch.test_comments` -> all comment endpoint routes currently return `404` (not implemented/wired yet). |
| `writing.tests` | 2026-03-25 02:38:40 UTC | PASS | `app/run_tests_quiet.sh writing.tests`; group-route assertion updated to current contract. |
| `mindmap.tests` | 2026-03-25 02:38:40 UTC | PASS | `app/run_tests_quiet.sh` default suite rerun; no-slash bulk endpoint assertions aligned with current routes. |
| `workbench.tests` | 2026-03-25 02:38:40 UTC | PASS | `app/run_tests_quiet.sh` default suite rerun; new Workbench Curation backend coverage added. |
| `projects.tests` | 2026-03-25 02:38:40 UTC | PASS | `app/run_tests_quiet.sh` default suite rerun; outsider permission assertions aligned with current opaque-not-found behavior. |
