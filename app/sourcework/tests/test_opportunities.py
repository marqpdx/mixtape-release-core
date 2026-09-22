import json
from datetime import datetime, timezone
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from groups.models import Group
from initiatives.models import Initiative
from sourcework.models import ProvisionalData, SourceEvidence, WorkingSet
from sourcework.opportunities.contracts import OpportunitySearchProfile, OpportunitySourceObservation
from sourcework.opportunities.dice import DiceOpportunityAdapter
from sourcework.opportunities.services import (
    ingest_opportunity_observations,
    provision_public_opportunity_source,
)


User = get_user_model()
FIXTURES = Path(__file__).parent / "fixtures"


class OpportunityIngestTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="opportunity-user", email="opportunity@example.com", password="pass")
        user_ct = ContentType.objects.get_for_model(User)
        self.group = Group.objects.create(
            title="Opportunity Group",
            slug="opportunity-group",
            description="Test group",
            group_type="community",
            decorators=[],
            additional_permissions=[],
            sponsor_content_type=user_ct,
            sponsor_object_id=self.user.id,
        )
        group_ct = ContentType.objects.get_for_model(Group)
        self.initiative = Initiative.objects.create(
            title="Opportunity Search",
            sponsor_content_type=group_ct,
            sponsor_object_id=self.group.id,
        )
        self.profile = OpportunitySearchProfile(
            profile_id="mark-current",
            version="2026-09-22",
            geography=("United States remote", "Portland hybrid"),
            engagement_types=("contract", "fractional", "part-time"),
            strong_technologies=("Python", "Django", "FastAPI"),
        )
        self.adapter = DiceOpportunityAdapter()
        self.grant = provision_public_opportunity_source(
            group=self.group,
            initiative=self.initiative,
            user=self.user,
        )

    def test_public_dice_grant_is_credentialless_and_cannot_submit(self):
        connection = self.grant.connection

        self.assertEqual(connection.provider, "dice")
        self.assertEqual(connection.provider_account_id, "public")
        self.assertEqual(connection.credential_payload, "")
        self.assertEqual(connection.metadata["access_mode"], "public")
        self.assertEqual(self.grant.resource_kind, "public_search")
        self.assertEqual(self.grant.capabilities, ["search", "read_detail"])
        self.assertFalse(self.grant.metadata["submission_allowed"])

    def test_valid_observation_becomes_evidence_provisional_data_and_working_set(self):
        result = self._ingest("dice_valid_remote_contract.json")

        self.assertEqual(result.observations_seen, 1)
        self.assertEqual(result.evidence_created, 1)
        self.assertEqual(result.provisional_created, 1)
        record = ProvisionalData.objects.get(source_external_id="dice-valid-001")
        self.assertEqual(record.normalized_payload["validation_status"], "valid")
        self.assertEqual(record.normalized_payload["application_action"], "outbound_email_available")
        self.assertEqual(record.source_evidence.provider, "dice")
        working_set = WorkingSet.objects.get(id=result.working_set_id)
        self.assertEqual(working_set.search_brief["profile_id"], "mark-current")
        self.assertEqual(working_set.summary["materialized"], 1)

    def test_contradictory_arrangement_is_retained_for_human_review(self):
        self._ingest("dice_contradictory_remote_onsite.json")

        record = ProvisionalData.objects.get(source_external_id="dice-contradictory-001")
        self.assertEqual(record.normalized_payload["validation_status"], "contradictory")
        self.assertIn(
            "remote_prose_conflicts_with_structured_onsite",
            record.normalized_payload["validation_findings"],
        )
        self.assertEqual(record.normalized_payload["application_action"], "manual_application_required")

    def test_repeated_observation_updates_existing_record_without_duplicate_evidence(self):
        first = self._ingest("dice_valid_remote_contract.json")
        second = self._ingest("dice_valid_remote_contract.json")

        self.assertEqual(first.provisional_created, 1)
        self.assertEqual(second.provisional_created, 0)
        self.assertEqual(second.provisional_updated, 1)
        self.assertEqual(ProvisionalData.objects.filter(source_external_id="dice-valid-001").count(), 1)
        self.assertEqual(SourceEvidence.objects.filter(provider_message_id="dice-valid-001").count(), 1)
        self.assertEqual(WorkingSet.objects.filter(source="dice").count(), 2)

    def _ingest(self, fixture_name: str):
        raw = json.loads((FIXTURES / fixture_name).read_text())
        observation = OpportunitySourceObservation(
            provider="dice",
            external_id=raw["external_id"],
            canonical_url=raw["canonical_url"],
            retrieved_at=datetime(2026, 9, 22, 18, 0, tzinfo=timezone.utc),
            observed_at=datetime(2026, 9, 22, 15, 0, tzinfo=timezone.utc),
            relevant_text=raw["description"],
            raw_payload=raw,
        )
        return ingest_opportunity_observations(
            source_grant=self.grant,
            search_profile=self.profile,
            observations=[observation],
            adapter=self.adapter,
            user=self.user,
        )
