import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.test import TestCase
from rest_framework.test import APIClient

from initiatives.models import ActionRun, ActionRunStatus, RunSeries, RunSeriesStatus
from surfaces.services.argus_switchboard_client import ArgusSwitchboardError, NotReachable

User = get_user_model()

BLOCK_MD = """---
block: help-fidelity-01
domain: help
block_state: ready
finding_types:
- outdated-description
---

# Block
"""


class ArgusApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.superuser = User.objects.create_superuser(
            username="argus_super", email="argus_super@example.com", password="testpass123",
        )
        self.member = User.objects.create_user(
            username="argus_member", email="argus_member@example.com", password="testpass123",
        )
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        root = Path(self.tmpdir.name)
        (root / "decisions" / "argus" / "audit-blocks").mkdir(parents=True)
        (root / "decisions" / "argus" / "audit-blocks" / "help-fidelity-01.md").write_text(BLOCK_MD)
        self.puddlejump_override = override_settings(PUDDLEJUMP_PATH=str(root))
        self.puddlejump_override.enable()
        self.addCleanup(self.puddlejump_override.disable)

    def test_blocks_list_requires_superuser(self):
        self.client.force_authenticate(self.member)
        response = self.client.get("/api/argus/blocks/")
        self.assertEqual(response.status_code, 403)

    def test_blocks_list_available_with_puddlejump_path_set(self):
        self.client.force_authenticate(self.superuser)
        response = self.client.get("/api/argus/blocks/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["available"])
        self.assertEqual(len(response.data["blocks"]), 1)
        self.assertEqual(response.data["blocks"][0]["slug"], "help-fidelity-01")
        self.assertIsNone(response.data["blocks"][0]["active_series_id"])

    def test_blocks_list_unavailable_without_puddlejump_path(self):
        self.puddlejump_override.disable()
        with override_settings(PUDDLEJUMP_PATH=None):
            self.client.force_authenticate(self.superuser)
            response = self.client.get("/api/argus/blocks/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["available"])
        self.puddlejump_override.enable()

    def test_run_now_is_not_reachable_and_records_an_action_run(self):
        # ARGUS_SWITCHBOARD_URL is unset in test settings, so this exercises
        # the client's own unset-URL degrade -- no mocking needed, same as
        # before this view was wired to the client.
        self.client.force_authenticate(self.superuser)
        response = self.client.post("/api/argus/blocks/help-fidelity-01/run/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "not_reachable")

        detail = self.client.get("/api/argus/blocks/help-fidelity-01/")
        self.assertEqual(len(detail.data["runs"]), 1)
        self.assertEqual(detail.data["runs"][0]["status"], "failed")

    def test_run_now_succeeds_when_switchboard_is_reachable(self):
        self.client.force_authenticate(self.superuser)
        with patch("surfaces.api.views.switchboard_start_run") as mock_start_run:
            mock_start_run.return_value = {"status": "started", "tool": "argus.start_run", "reason": ""}
            response = self.client.post("/api/argus/blocks/help-fidelity-01/run/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "started")

        run = ActionRun.objects.get(tool_name="argus.start_run")
        self.assertEqual(run.status, ActionRunStatus.SUCCEEDED)
        self.assertEqual(run.result_payload["status"], "started")

    def test_run_now_not_reachable_from_switchboard_itself_records_the_cause(self):
        self.client.force_authenticate(self.superuser)
        with patch("surfaces.api.views.switchboard_start_run") as mock_start_run:
            mock_start_run.return_value = NotReachable("Switchboard error 503: unavailable")
            response = self.client.post("/api/argus/blocks/help-fidelity-01/run/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "not_reachable")
        self.assertIn("503", response.data["detail"])

        run = ActionRun.objects.get(tool_name="argus.start_run")
        self.assertEqual(run.status, ActionRunStatus.FAILED)
        self.assertEqual(run.error_payload["reason"], "not_reachable")

    def test_run_now_validation_error_from_switchboard_returns_400(self):
        self.client.force_authenticate(self.superuser)
        with patch("surfaces.api.views.switchboard_start_run") as mock_start_run:
            mock_start_run.side_effect = ArgusSwitchboardError(
                "Switchboard rejected the request (422).", status_code=422, body="bad payload",
            )
            response = self.client.post("/api/argus/blocks/help-fidelity-01/run/")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["status"], "error")

        run = ActionRun.objects.get(tool_name="argus.start_run")
        self.assertEqual(run.status, ActionRunStatus.FAILED)
        self.assertEqual(run.error_payload["reason"], "validation_error")
        self.assertEqual(run.error_payload["status_code"], 422)

    def test_run_series_create_get_stop(self):
        self.client.force_authenticate(self.superuser)
        create = self.client.post(
            "/api/argus/series/",
            {
                "block_slug": "help-fidelity-01",
                "cadence_hours": 2,
                "span": {"kind": "days", "value": 3},
                "per_turn_caps": {
                    "max_tokens": 50000,
                    "max_turns": 20,
                    "max_wall_clock_seconds": 600,
                },
            },
            format="json",
        )
        self.assertEqual(create.status_code, 201)
        series_id = create.data["series_id"]
        self.assertEqual(create.data["status"], "active")
        self.assertEqual(create.data["day_of_span"], 1)

        # Now the blocks list shows it inline, per the decided fork.
        blocks = self.client.get("/api/argus/blocks/")
        self.assertEqual(blocks.data["blocks"][0]["active_series_id"], series_id)

        get_response = self.client.get(f"/api/argus/series/{series_id}/")
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.data["series_id"], series_id)

        stop_response = self.client.post(f"/api/argus/series/{series_id}/stop/")
        self.assertEqual(stop_response.status_code, 200)
        self.assertEqual(stop_response.data["status"], "stopped")
        self.assertEqual(RunSeries.objects.get(pk=series_id).status, RunSeriesStatus.STOPPED)

    def test_run_series_rejects_span_over_seven_days(self):
        self.client.force_authenticate(self.superuser)
        response = self.client.post(
            "/api/argus/series/",
            {
                "block_slug": "help-fidelity-01",
                "cadence_hours": 2,
                "span": {"kind": "days", "value": 10},
                "per_turn_caps": {"max_tokens": 1000, "max_turns": 5, "max_wall_clock_seconds": 60},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_run_series_rejects_run_count_span_over_seven_days(self):
        self.client.force_authenticate(self.superuser)
        response = self.client.post(
            "/api/argus/series/",
            {
                "block_slug": "help-fidelity-01",
                "cadence_hours": 24,
                "span": {"kind": "runs", "value": 100},
                "per_turn_caps": {"max_tokens": 1000, "max_turns": 5, "max_wall_clock_seconds": 60},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("span", response.data)

    def test_run_series_rejects_negative_per_turn_caps(self):
        self.client.force_authenticate(self.superuser)
        response = self.client.post(
            "/api/argus/series/",
            {
                "block_slug": "help-fidelity-01",
                "cadence_hours": 2,
                "span": {"kind": "days", "value": 3},
                "per_turn_caps": {"max_tokens": -1, "max_turns": 5, "max_wall_clock_seconds": 60},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("per_turn_caps", response.data)

    def test_run_series_rejects_missing_per_turn_caps(self):
        self.client.force_authenticate(self.superuser)
        response = self.client.post(
            "/api/argus/series/",
            {
                "block_slug": "help-fidelity-01",
                "cadence_hours": 2,
                "span": {"kind": "days", "value": 3},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("per_turn_caps", response.data)

    def test_run_series_rejects_missing_per_turn_caps_key(self):
        self.client.force_authenticate(self.superuser)
        response = self.client.post(
            "/api/argus/series/",
            {
                "block_slug": "help-fidelity-01",
                "cadence_hours": 2,
                "span": {"kind": "days", "value": 3},
                "per_turn_caps": {"max_tokens": 1000},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("per_turn_caps", response.data)

    def test_run_series_rejects_unknown_block_slug(self):
        self.client.force_authenticate(self.superuser)
        response = self.client.post(
            "/api/argus/series/",
            {
                "block_slug": "abe-no-such-block",
                "cadence_hours": 2,
                "span": {"kind": "days", "value": 3},
                "per_turn_caps": {"max_tokens": 1000, "max_turns": 5, "max_wall_clock_seconds": 60},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("block_slug", response.data)

    def test_run_series_rejects_block_not_ready(self):
        root = Path(self.tmpdir.name)
        (root / "decisions" / "argus" / "audit-blocks" / "not-ready-block.md").write_text(
            BLOCK_MD.replace("help-fidelity-01", "not-ready-block").replace(
                "block_state: ready", "block_state: draft"
            )
        )
        self.client.force_authenticate(self.superuser)
        response = self.client.post(
            "/api/argus/series/",
            {
                "block_slug": "not-ready-block",
                "cadence_hours": 2,
                "span": {"kind": "days", "value": 3},
                "per_turn_caps": {"max_tokens": 1000, "max_turns": 5, "max_wall_clock_seconds": 60},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("block_slug", response.data)
