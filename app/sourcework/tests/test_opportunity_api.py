from datetime import datetime, timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from sourcework.models import (
    ExternalConnection,
    OpportunityApplicationDraft,
    OpportunityProfile,
    ProvisionalData,
    ProvisionalDataMembership,
    WorkingSet,
)
from sourcework.opportunities.contracts import OpportunitySourceObservation
from sourcework.opportunities.dice_mcp import DiceSearchBatch, plan_dice_queries


User = get_user_model()


def _profile_payload():
    return {
        "name": "Current search",
        "resume_label": "Resume v4.2",
        "resume_version": "0.4.2",
        "query_lanes": [
            {
                "id": "python-platform",
                "label": "Python platform",
                "keyword": "Senior Python Django FastAPI",
                "enabled": True,
            }
        ],
        "target_roles": ["Senior Python Engineer"],
        "geography": ["United States"],
        "workplace_types": ["Remote"],
        "employment_types": ["CONTRACTS"],
        "seniority": ["senior", "staff"],
        "strong_domains": ["platform"],
        "strong_technologies": ["Python", "Django", "FastAPI"],
        "exclusions": ["computer vision"],
        "freshness_hours": 72,
        "preferences": {"results_per_lane": 8},
    }


class OpportunityAPIProfileTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="member-one", password="pass")
        self.other_user = User.objects.create_user(username="member-two", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_profile_versions_are_member_owned(self):
        first = self.client.put("/api/opportunities/profile", _profile_payload(), format="json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.data["profile"]["version"], 1)

        revised = {**_profile_payload(), "freshness_hours": 24}
        second = self.client.put("/api/opportunities/profile", revised, format="json")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data["profile"]["version"], 2)
        self.assertEqual(OpportunityProfile.objects.filter(owner_user=self.user).count(), 2)
        self.assertEqual(OpportunityProfile.objects.filter(owner_user=self.user, is_current=True).count(), 1)

        self.client.force_authenticate(self.other_user)
        response = self.client.get("/api/opportunities/profile")
        self.assertIsNone(response.data["profile"])

    def test_query_plan_maps_profile_to_dice_filters(self):
        profile = OpportunityProfile.objects.create(owner_user=self.user, **_profile_payload())
        query = plan_dice_queries(profile)[0]

        self.assertEqual(query["arguments"]["keyword"], "Senior Python Django FastAPI")
        self.assertEqual(query["arguments"]["posted_date"], "THREE")
        self.assertEqual(query["arguments"]["workplace_types"], ["Remote"])
        self.assertEqual(query["arguments"]["jobs_per_page"], 8)


class OpportunityAPISearchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="search-member", password="pass")
        self.other_user = User.objects.create_user(username="other-search-member", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.profile = OpportunityProfile.objects.create(owner_user=self.user, **_profile_payload())

    @patch("sourcework.api.opportunity_views.acquire_dice_search")
    def test_search_creates_member_owned_working_set_and_candidates(self, acquire):
        now = datetime(2026, 9, 22, 18, 0, tzinfo=timezone.utc)
        acquire.return_value = DiceSearchBatch(
            observations=(
                OpportunitySourceObservation(
                    provider="dice",
                    external_id="dice-member-1",
                    canonical_url="https://www.dice.com/job-detail/dice-member-1",
                    retrieved_at=now,
                    observed_at=now,
                    relevant_text="Senior Python platform role using Django.",
                    raw_payload={
                        "title": "Senior Python Platform Engineer",
                        "organization": "Example Co",
                        "description": "Senior Python platform role using Django.",
                        "arrangement": "Remote",
                        "engagement_type": "Contract",
                        "listing_status": "live",
                    },
                ),
            ),
            query_results=(
                {
                    "lane_id": "python-platform",
                    "lane_label": "Python platform",
                    "arguments": {"keyword": "Senior Python Django FastAPI"},
                    "returned": 1,
                    "available": 1,
                    "search_id": "search-1",
                },
            ),
        )

        response = self.client.post("/api/opportunities/search-runs", {}, format="json")

        self.assertEqual(response.status_code, 201)
        working_set = WorkingSet.objects.get(id=response.data["run"]["id"])
        self.assertIsNone(working_set.group_id)
        self.assertEqual(working_set.owner_user, self.user)
        self.assertEqual(working_set.execution_metadata["transport"], "official_dice_mcp")
        connection = ExternalConnection.objects.get(owner=self.user, provider="dice")
        self.assertIsNone(connection.group_id)
        self.assertEqual(connection.credential_payload, "")
        candidate = ProvisionalData.objects.get(owner_user=self.user, source_external_id="dice-member-1")
        self.assertEqual(candidate.normalized_payload["preliminary_fit"]["label"], "promising")

    def test_candidate_state_cannot_cross_member_boundary(self):
        other = User.objects.create_user(username="other-member", password="pass")
        record = ProvisionalData.objects.create(
            owner_user=other,
            kind="opportunity_candidate",
            source_type="dice",
            source_external_id="private-opportunity",
        )

        response = self.client.patch(
            f"/api/opportunities/candidates/{record.id}/state",
            {"state": "interesting"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)

    @patch("sourcework.api.opportunity_views.DiceMCPClient.get_job_details")
    def test_full_details_become_readable_and_preserve_application_metadata(self, get_details):
        record, _ = self._candidate(
            raw_payload={
                "easyApply": True,
                "employerType": "Recruiter",
                "detailsPageUrl": "https://www.dice.com/job-detail/detail-1",
            },
        )
        get_details.return_value = {
            "description": (
                "<h2>Role</h2><p>Build secure platforms.</p>"
                "<ul><li>Python</li><li>Contact recruiter@example.com</li></ul>"
                "<script>alert('no')</script>"
            ),
            "skills": [{"name": "Python"}],
        }

        response = self.client.post(f"/api/opportunities/candidates/{record.id}/details", {}, format="json")

        self.assertEqual(response.status_code, 200)
        record.refresh_from_db()
        payload = record.normalized_payload
        self.assertEqual(payload["description"], "Role\n\nBuild secure platforms.\n\n- Python\n- Contact recruiter@example.com")
        self.assertNotIn("script", payload["description"])
        self.assertTrue(payload["easy_apply"])
        self.assertEqual(payload["employer_type"], "Recruiter")
        self.assertEqual(payload["application_method"], "recruiter_email")
        self.assertEqual(payload["contact_email"], "recruiter@example.com")
        self.assertEqual(record.raw_payload["details"], get_details.return_value)

    @patch("sourcework.opportunities.application.service_generate")
    def test_application_draft_is_editable_and_member_owned(self, service_generate):
        record, _ = self._candidate(
            normalized_payload={
                "title": "Senior Platform Engineer",
                "organization": "Example Co",
                "description": "Build a Python platform.",
                "detail_acquired_at": "2026-09-22T20:00:00Z",
                "easy_apply": True,
            },
        )
        service_generate.return_value = {
            "result": {"body": "I am interested in the role.\n\nMy Python background aligns with the work."}
        }

        generated = self.client.post(
            f"/api/opportunities/candidates/{record.id}/application-draft",
            {},
            format="json",
        )

        self.assertEqual(generated.status_code, 201)
        self.assertEqual(generated.data["draft"]["resume_version"], self.profile.resume_version)
        draft = OpportunityApplicationDraft.objects.get(owner_user=self.user, opportunity=record)
        self.assertEqual(draft.generated_by, "inkwell")
        self.assertEqual(draft.generation_context["opportunity"]["title"], "Senior Platform Engineer")

        edited = self.client.put(
            f"/api/opportunities/candidates/{record.id}/application-draft",
            {"letter_body": "A reviewed and edited letter.", "status": "ready"},
            format="json",
        )
        self.assertEqual(edited.status_code, 200)
        draft.refresh_from_db()
        self.assertEqual(draft.letter_body, "A reviewed and edited letter.")
        self.assertEqual(draft.status, "ready")

        self.client.force_authenticate(self.other_user)
        hidden = self.client.get(f"/api/opportunities/candidates/{record.id}/application-draft")
        self.assertEqual(hidden.status_code, 404)

    @patch("sourcework.api.opportunity_views.render_cover_letter_pdf", return_value=b"%PDF-cover")
    def test_application_pdf_is_downloadable(self, render_pdf):
        record, _ = self._candidate(
            normalized_payload={"title": "Platform Engineer", "organization": "Example Co"},
        )
        draft = OpportunityApplicationDraft.objects.create(
            owner_user=self.user,
            opportunity=record,
            profile=self.profile,
            letter_body="Reviewed letter.",
        )

        response = self.client.get(f"/api/opportunities/candidates/{record.id}/application-draft/pdf")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"%PDF-cover")
        self.assertEqual(response["Content-Type"], "application/pdf")
        render_pdf.assert_called_once_with(draft=draft)

    def _candidate(self, *, raw_payload=None, normalized_payload=None):
        working_set = WorkingSet.objects.create(
            owner_user=self.user,
            title="Test opportunities",
            purpose="Test",
            source="dice",
        )
        record = ProvisionalData.objects.create(
            owner_user=self.user,
            kind="opportunity_candidate",
            source_type="dice",
            source_external_id=f"candidate-{working_set.id}",
            source_locator="https://www.dice.com/job-detail/test",
            raw_payload=raw_payload or {},
            normalized_payload=normalized_payload or {
                "title": "Platform Engineer",
                "organization": "Example Co",
            },
        )
        ProvisionalDataMembership.objects.create(working_set=working_set, provisional_data=record)
        return record, working_set
