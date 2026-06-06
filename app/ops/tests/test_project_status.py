from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient


class ProjectStatusTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.superuser = User.objects.create_user(
            username="ops_admin",
            password="password",
            is_superuser=True,
            is_staff=True,
        )
        self.user = User.objects.create_user(
            username="regular_user",
            password="password",
        )

    def test_project_status_requires_superuser(self):
        response = self.client.get("/api/ops/project-status")
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/ops/project-status")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @override_settings(PUDDLEJUMP_PATH=None)
    def test_project_status_unavailable_without_path(self):
        self.client.force_authenticate(user=self.superuser)
        response = self.client.get("/api/ops/project-status")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["available"])
        self.assertEqual(response.data["decisions"], [])
        self.assertEqual(response.data["timeline"], [])
        self.assertEqual(response.data["unprocessed_inbox_count"], 0)

    def test_project_status_reads_decisions_canonical_build_log_and_inbox(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            decisions_dir = root / "decisions" / "example-adr"
            decisions_dir.mkdir(parents=True)
            (decisions_dir / "example-adr.md").write_text(
                "\n".join(
                    [
                        "> **Status:** Canon",
                        "> **Class:** adr",
                        "> **Library:** decisions/example-adr/",
                        "",
                        "# Example ADR",
                        "",
                        "| # | Name | Status |",
                        "|---|------|--------|",
                        "| EX-1 | First step | ✅ |",
                        "| EX-2 | Second step | 🔲 |",
                    ]
                ),
                encoding="utf-8",
            )

            (root / "build-log.md").write_text(
                "\n".join(
                    [
                        "> **Status:** Canon",
                        "> **Class:** log",
                        "",
                        "# System Build Log",
                        "",
                        "## Log",
                        "",
                        "### 2026-06-04 — mixtape-release-core `abc1234`",
                        "",
                        "Canonical version of the example status surface.",
                        "",
                        "_Work effort: Example ADR_",
                        "",
                        "---",
                        "",
                        "### 2026-06-03 — mixtape-release-frontend `def5678` + `fed4321`",
                        "",
                        "Built the companion status UI in two frontend commits.",
                        "",
                        "_Work effort: Example ADR UI_",
                    ]
                ),
                encoding="utf-8",
            )

            inbox_dir = root / "build-log-inbox"
            inbox_dir.mkdir()
            (inbox_dir / "2026-06-05-example-abc1234.md").write_text(
                "\n".join(
                    [
                        "---",
                        "repo: mixtape-release-core",
                        "commit: abc1234 — Add example",
                        "date: 2026-06-05",
                        "work_effort: Example ADR",
                        "---",
                        "",
                        "Inbox copy that should be deduped against canonical history.",
                    ]
                ),
                encoding="utf-8",
            )
            (inbox_dir / "2026-06-05-example-xyz9876.md").write_text(
                "\n".join(
                    [
                        "---",
                        "repo: mixtape-release-core",
                        "commit: xyz9876 — Add unswept example",
                        "date: 2026-06-05",
                        "work_effort: Example ADR",
                        "---",
                        "",
                        "Implemented the unswept example status surface.",
                    ]
                ),
                encoding="utf-8",
            )

            with override_settings(PUDDLEJUMP_PATH=str(root)):
                self.client.force_authenticate(user=self.superuser)
                response = self.client.get("/api/ops/project-status")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["available"])
        self.assertEqual(len(response.data["decisions"]), 1)
        self.assertEqual(response.data["decisions"][0]["name"], "Example ADR")
        self.assertEqual(response.data["decisions"][0]["queue_state"], "in_progress")
        self.assertEqual(response.data["decisions"][0]["checkpoint_counts"]["done"], 1)
        self.assertEqual(response.data["decisions"][0]["checkpoint_counts"]["pending"], 1)
        self.assertEqual(response.data["unprocessed_inbox_count"], 2)
        self.assertEqual(len(response.data["timeline"]), 4)

        timeline_by_commit = {entry["commit_hash"]: entry for entry in response.data["timeline"]}
        self.assertEqual(timeline_by_commit["abc1234"]["source"], "build_log")
        self.assertEqual(timeline_by_commit["abc1234"]["body"], "Canonical version of the example status surface.")
        self.assertEqual(timeline_by_commit["xyz9876"]["source"], "inbox")
        self.assertEqual(timeline_by_commit["xyz9876"]["commit_message"], "Add unswept example")
        self.assertEqual(timeline_by_commit["def5678"]["repo"], "mixtape-release-frontend")
        self.assertEqual(timeline_by_commit["fed4321"]["repo"], "mixtape-release-frontend")
