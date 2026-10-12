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

    def test_project_status_reads_yaml_frontmatter_and_quoted_inbox_commit(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            decisions_dir = root / "decisions" / "yaml-adr"
            decisions_dir.mkdir(parents=True)
            (decisions_dir / "yaml-adr.md").write_text(
                "\n".join(
                    [
                        "---",
                        "title: YAML ADR",
                        "status: canon",
                        "class: adr",
                        "library: decisions/yaml-adr/",
                        "created: 2026-10-01",
                        "last_updated: 2026-10-11",
                        "related_to:",
                        "  - decisions/other.md",
                        "---",
                        "",
                        "# YAML ADR",
                        "",
                        "> **Headnote (2026-10-11):** A note about this document.",
                        "",
                        "| # | Name | Status |",
                        "|---|------|--------|",
                        "| Y-1 | Only step | ✅ |",
                    ]
                ),
                encoding="utf-8",
            )
            (decisions_dir / "closed-block.md").write_text(
                "\n".join(
                    [
                        "---",
                        "title: Closed Block",
                        "status: canon",
                        "class: spec",
                        "block_state: closed",
                        "---",
                        "",
                        "# Closed Block",
                    ]
                ),
                encoding="utf-8",
            )
            inbox_dir = root / "build-log-inbox"
            inbox_dir.mkdir()
            (inbox_dir / "2026-10-11-example-q1w2e3r.md").write_text(
                "\n".join(
                    [
                        "---",
                        "repo: mixtape-release-core",
                        'commit: "q1w2e3r — feat(ops): read: YAML #frontmatter"',
                        "date: 2026-10-11",
                        "work_effort: Example ADR",
                        "---",
                        "",
                        "Quoted commit field, per the current inbox template.",
                    ]
                ),
                encoding="utf-8",
            )

            with override_settings(PUDDLEJUMP_PATH=str(root)):
                self.client.force_authenticate(user=self.superuser)
                response = self.client.get("/api/ops/project-status")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        decisions = {row["name"]: row for row in response.data["decisions"]}
        self.assertEqual(decisions["YAML ADR"]["status"], "canon")
        self.assertEqual(decisions["YAML ADR"]["class"], "adr")
        self.assertEqual(decisions["YAML ADR"]["library"], "decisions/yaml-adr/")
        self.assertEqual(decisions["YAML ADR"]["last_updated"], "2026-10-11")
        self.assertEqual(decisions["YAML ADR"]["queue_state"], "complete")
        self.assertEqual(decisions["Closed Block"]["queue_state"], "complete")

        timeline_by_commit = {entry["commit_hash"]: entry for entry in response.data["timeline"]}
        self.assertIn("q1w2e3r", timeline_by_commit)
        self.assertEqual(timeline_by_commit["q1w2e3r"]["commit_message"], "feat(ops): read: YAML #frontmatter")
