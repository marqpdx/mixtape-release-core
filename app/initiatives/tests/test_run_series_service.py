from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from initiatives.models import Initiative, InitiativeStatus, RunSeries, RunSeriesSpanKind, RunSeriesStatus
from initiatives.services.run_series import close_elapsed_series, due_run_series

User = get_user_model()


class RunSeriesServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="runseries_service_user")
        self.initiative = Initiative.objects.create(
            title="Argus help-fidelity-01",
            sponsor_content_type=ContentType.objects.get_for_model(User),
            sponsor_object_id=self.user.pk,
            status=InitiativeStatus.ACTIVE,
        )

    def _series(self, **overrides):
        defaults = dict(
            initiative=self.initiative,
            block_slug="help-fidelity-01",
            cadence_hours=2,
            span_kind=RunSeriesSpanKind.DAYS,
            span_value=3,
            started_by=self.user,
        )
        defaults.update(overrides)
        return RunSeries.objects.create(**defaults)

    def test_freshly_created_series_is_not_yet_due(self):
        rs = self._series()
        self.assertNotIn(rs, due_run_series())

    def test_series_past_its_cadence_is_due(self):
        rs = self._series()
        RunSeries.objects.filter(pk=rs.pk).update(created_at=timezone.now() - timedelta(hours=3))
        self.assertIn(rs, due_run_series())

    def test_elapsed_days_span_is_closed_not_due(self):
        rs = self._series(span_value=1)
        RunSeries.objects.filter(pk=rs.pk).update(created_at=timezone.now() - timedelta(days=2))
        closed = close_elapsed_series()
        self.assertIn(rs, closed)
        self.assertEqual(RunSeries.objects.get(pk=rs.pk).status, RunSeriesStatus.COMPLETED)
        self.assertNotIn(rs, due_run_series())

    def test_runs_span_reaching_its_count_is_closed(self):
        from initiatives.models import ActionRun, ActionRunInitiatorType

        rs = self._series(span_kind=RunSeriesSpanKind.RUNS, span_value=1)
        ActionRun.objects.create(
            run_series=rs,
            tool_name="argus.start_run",
            tenant_id=self.user.pk,
            tenant_namespace="t",
            initiator_type=ActionRunInitiatorType.HUMAN,
            initiator_id=str(self.user.pk),
        )
        closed = close_elapsed_series()
        self.assertIn(rs, closed)
