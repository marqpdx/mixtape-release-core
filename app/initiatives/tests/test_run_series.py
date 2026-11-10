from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.test import TestCase

from initiatives.models import (
    ActionRun,
    ActionRunInitiatorType,
    Initiative,
    InitiativeStatus,
    RunSeries,
    RunSeriesSpanKind,
)

User = get_user_model()


class RunSeriesTests(TestCase):
    """ADR-0064 D9: a run series is the consent record (AC-4d)."""

    def setUp(self):
        self.user = User.objects.create(username="runseries_user")
        self.initiative = Initiative.objects.create(
            title="Argus help-fidelity-01",
            sponsor_content_type=ContentType.objects.get_for_model(User),
            sponsor_object_id=self.user.pk,
            status=InitiativeStatus.ACTIVE,
        )

    def test_bounded_days_series_and_derived_fields(self):
        rs = RunSeries(
            initiative=self.initiative,
            block_slug="help-fidelity-01",
            cadence_hours=2,
            span_kind=RunSeriesSpanKind.DAYS,
            span_value=3,
            started_by=self.user,
        )
        rs.full_clean(exclude=["per_turn_caps"])
        rs.save()

        self.assertEqual(rs.runs_done, 0)
        self.assertIsNone(rs.runs_total)
        self.assertEqual(rs.day_of_span, 1)
        self.assertEqual(rs.findings_count, 0)

        ActionRun.objects.create(
            run_series=rs,
            tool_name="argus.start_run",
            tenant_id=self.user.pk,
            tenant_namespace="t",
            initiator_type=ActionRunInitiatorType.HUMAN,
            initiator_id=str(self.user.pk),
        )
        self.assertEqual(RunSeries.objects.get(pk=rs.pk).runs_done, 1)

    def test_stop_is_immediate(self):
        rs = RunSeries.objects.create(
            initiative=self.initiative,
            block_slug="help-fidelity-01",
            cadence_hours=2,
            span_kind=RunSeriesSpanKind.DAYS,
            span_value=3,
            started_by=self.user,
        )
        rs.stop()
        self.assertEqual(rs.status, "stopped")
        self.assertIsNotNone(rs.stopped_at)

    def test_span_over_seven_days_rejected(self):
        """D9: a bounded series lasts at most seven days."""
        bad = RunSeries(
            initiative=self.initiative,
            block_slug="help-fidelity-01",
            cadence_hours=2,
            span_kind=RunSeriesSpanKind.DAYS,
            span_value=10,
            started_by=self.user,
        )
        with self.assertRaises(ValidationError):
            bad.full_clean(exclude=["per_turn_caps"])

    def test_runs_span_has_fixed_total(self):
        rs = RunSeries.objects.create(
            initiative=self.initiative,
            block_slug="help-fidelity-01",
            cadence_hours=2,
            span_kind=RunSeriesSpanKind.RUNS,
            span_value=36,
            started_by=self.user,
        )
        self.assertEqual(rs.runs_total, 36)
        self.assertIsNone(rs.day_of_span)
