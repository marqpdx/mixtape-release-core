from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from initiatives.models import (
    ActionRun,
    ActionRunInitiatorType,
    Artifact,
    ArtifactKind,
    Initiative,
    InitiativeStatus,
    RunSeries,
    RunSeriesSpanKind,
)
from initiatives.services.findings import FindingsShapeError, create_findings_artifact

User = get_user_model()


def _payload(**overrides):
    payload = {
        "shape_id": "argus.findings",
        "shape_version": "0.1.0",
        "block_id": "help-fidelity-01",
        "block_version": "1",
        "run_id": "r1",
        "started_at": "2026-11-09T00:00:00Z",
        "finished_at": "2026-11-09T00:05:00Z",
        "outcome": "clean",
        "reviewed": [{"ref": "content/help/x.md"}],
        "findings": [],
        "uncertain": [],
    }
    payload.update(overrides)
    return payload


class FindingsArtifactTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="findings_user")
        self.initiative = Initiative.objects.create(
            title="Argus help-fidelity-01",
            sponsor_content_type=ContentType.objects.get_for_model(User),
            sponsor_object_id=self.user.pk,
            status=InitiativeStatus.ACTIVE,
        )
        self.run = ActionRun.objects.create(
            initiative=self.initiative,
            tool_name="argus.start_run",
            tenant_id=self.user.pk,
            tenant_namespace="t",
            initiator_type=ActionRunInitiatorType.HUMAN,
            initiator_id=str(self.user.pk),
        )

    def test_valid_payload_creates_findings_artifact(self):
        artifact = create_findings_artifact(action_run=self.run, payload=_payload())
        self.assertEqual(artifact.kind, ArtifactKind.FINDINGS)
        self.assertEqual(artifact.shape_id, "argus.findings")
        self.assertEqual(artifact.initiative_id, self.initiative.id)
        self.assertEqual(artifact.action_run_id, self.run.id)
        self.assertEqual(artifact.structured_data["outcome"], "clean")

    def test_found_outcome_without_findings_rejected(self):
        with self.assertRaises(FindingsShapeError):
            create_findings_artifact(action_run=self.run, payload=_payload(outcome="found"))

    def test_incomplete_without_outcome_reason_rejected(self):
        with self.assertRaises(FindingsShapeError):
            create_findings_artifact(action_run=self.run, payload=_payload(outcome="incomplete"))


class RunSeriesFindingsCountTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="findings_count_user")
        self.initiative = Initiative.objects.create(
            title="Argus help-fidelity-01",
            sponsor_content_type=ContentType.objects.get_for_model(User),
            sponsor_object_id=self.user.pk,
            status=InitiativeStatus.ACTIVE,
        )
        self.series = RunSeries.objects.create(
            initiative=self.initiative,
            block_slug="help-fidelity-01",
            cadence_hours=2,
            span_kind=RunSeriesSpanKind.DAYS,
            span_value=3,
            started_by=self.user,
        )

    def _run(self):
        return ActionRun.objects.create(
            initiative=self.initiative,
            run_series=self.series,
            tool_name="argus.start_run",
            tenant_id=self.user.pk,
            tenant_namespace="t",
            initiator_type=ActionRunInitiatorType.HUMAN,
            initiator_id=str(self.user.pk),
        )

    def test_findings_count_only_counts_non_empty_findings(self):
        clean_run = self._run()
        create_findings_artifact(action_run=clean_run, payload=_payload(run_id=str(clean_run.id)))
        self.assertEqual(self.series.findings_count, 0)

        found_run = self._run()
        create_findings_artifact(
            action_run=found_run,
            payload=_payload(
                run_id=str(found_run.id),
                outcome="found",
                findings=[{
                    "finding_id": "f1",
                    "type": "outdated-description",
                    "severity": "medium",
                    "confidence": "high",
                    "title": "Example",
                    "location": [{"ref": "content/help/x.md"}],
                    "issue": "Out of date.",
                    "recommendation": "Update it.",
                }],
            ),
        )
        self.assertEqual(self.series.findings_count, 1)
