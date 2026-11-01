from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from groups.models import Group
from initiatives.models import ActionRun
from sourcework.models import ProvisionalData, ProvisionalDataState

from heddle.errors import InterpretationError
from heddle.handoff import keep_sighting

User = get_user_model()

SIGHTING = {
    "sighting_id": "s-1",
    "shape_id": "shuttle.place",
    "shape_version": "0.1.0",
    "confidence": "high",
    "source_locator": [{"source_ref": "weave:1", "source_revision": 0, "start": 0, "end": 5, "quote": "Paris"}],
    "uncertain": [],
    "name_as_said": "Paris",
    "proposed_name": "Paris",
    "role": "named_place",
    "address_as_said": "",
}


class KeepSightingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="member")
        user_ct = ContentType.objects.get_for_model(User)
        self.group = Group.objects.create(
            title="Test Group",
            slug="test-group",
            description="Test group",
            group_type="community",
            decorators=[],
            additional_permissions=[],
            sponsor_content_type=user_ct,
            sponsor_object_id=self.user.id,
        )
        self.action_run = ActionRun.objects.create(
            tool_name="shuttle.weave",
            status="succeeded",
            tenant_id="00000000-0000-0000-0000-000000000001",
            tenant_namespace="platform:crossroads",
            initiator_type="human",
            initiator_id=str(self.user.pk),
        )

    def test_keep_creates_provisional_data_stamped_with_the_shape(self):
        record = keep_sighting(sighting=SIGHTING, action_run=self.action_run, group=self.group)

        self.assertEqual(record.shape_id, "shuttle.place")
        self.assertEqual(record.shape_version, "0.1.0")
        self.assertEqual(record.kind, "shuttle.place")
        self.assertEqual(record.state, ProvisionalDataState.NEW)
        self.assertEqual(record.group, self.group)
        self.assertEqual(record.confidence, 1.0)
        # The Shape's own fields, not the D8 envelope, land in normalized_payload.
        self.assertEqual(record.normalized_payload, {
            "name_as_said": "Paris", "proposed_name": "Paris",
            "role": "named_place", "address_as_said": "",
        })
        # Raw capture survives verbatim for later re-extraction.
        self.assertEqual(record.raw_payload, SIGHTING)

    def test_provenance_points_back_to_the_reading(self):
        record = keep_sighting(sighting=SIGHTING, action_run=self.action_run, group=self.group)

        self.assertEqual(record.provenance["weave_action_run_id"], str(self.action_run.pk))
        self.assertEqual(record.provenance["sighting_id"], "s-1")
        self.assertEqual(record.provenance["shape_id"], "shuttle.place")
        self.assertEqual(record.provenance["shape_version"], "0.1.0")

    def test_sponsor_required_no_fallback(self):
        with self.assertRaises(InterpretationError) as ctx:
            keep_sighting(sighting=SIGHTING, action_run=self.action_run)

        self.assertEqual(ctx.exception.code, "sponsor_required")
        self.assertFalse(ProvisionalData.objects.exists())

    def test_owner_user_alone_is_a_valid_sponsor(self):
        record = keep_sighting(sighting=SIGHTING, action_run=self.action_run, owner_user=self.user)

        self.assertEqual(record.owner_user, self.user)
        self.assertIsNone(record.group)

    def test_sighting_with_no_shape_fields_is_rejected_not_kept(self):
        envelope_only = {k: v for k, v in SIGHTING.items()
                         if k in {"sighting_id", "shape_id", "shape_version", "confidence",
                                  "source_locator", "uncertain"}}

        with self.assertRaises(InterpretationError) as ctx:
            keep_sighting(sighting=envelope_only, action_run=self.action_run, group=self.group)

        self.assertEqual(ctx.exception.code, "shape_fields_missing")
        self.assertEqual(ctx.exception.status, 422)
        self.assertFalse(ProvisionalData.objects.exists())

    def test_dismiss_is_simply_not_calling_keep_sighting(self):
        # D5: a dismissed Sighting fades. There is nothing to call and
        # nothing is persisted — this test documents that absence.
        self.assertFalse(ProvisionalData.objects.exists())
