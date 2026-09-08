from django.test import SimpleTestCase
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APIClient

from groups.models import Group
from initiatives.models import ActionRun, ActionRunStatus
from sourcework.models import NameConfidence, NameSource, NameStatus
from sourcework.models import ExternalConnection, ExternalConnectionStatus, ProvisionalThing, SourceGrant, WorkingSet
from sourcework.providers import SourceMessage, get_source_provider_adapter
from sourcework.services import import_latest_from_source_grant, resolve_sender_name
from switchboard.source_grants import SourceGrantAccessError, SourceGrantReadRequest, fetch_latest_messages_for_source_grant


User = get_user_model()


class ResolveSenderNameTests(SimpleTestCase):
    def test_prefers_confident_header_name(self):
        result = resolve_sender_name({
            "from_header": "Vaughn Smith <vaughn@example.com>",
            "body": "Best regards,\nSomeone Else",
        })

        self.assertEqual(result.preferred_name, "Vaughn Smith")
        self.assertEqual(result.email, "vaughn@example.com")
        self.assertEqual(result.source, NameSource.HEADER)
        self.assertEqual(result.confidence, NameConfidence.HIGH)
        self.assertEqual(result.status, NameStatus.READY)
        self.assertEqual(result.evidence_excerpt, "")

    def test_uses_signature_when_header_name_is_missing(self):
        result = resolve_sender_name({
            "from_header": "talent@example.net",
            "body": "Hello,\n\nKind regards,\nAmara Lee\nTalent Partner",
        })

        self.assertEqual(result.preferred_name, "Amara Lee")
        self.assertEqual(result.email, "talent@example.net")
        self.assertEqual(result.source, NameSource.SIGNATURE)
        self.assertEqual(result.confidence, NameConfidence.HIGH)
        self.assertEqual(result.status, NameStatus.READY)
        self.assertIn("Kind regards", result.evidence_excerpt)
        self.assertIn("Amara Lee", result.evidence_excerpt)

    def test_marks_unclear_name_for_review(self):
        result = resolve_sender_name({
            "from_header": "recruiting@example.org",
            "body": "Hello,\n\nThis role may interest you.",
        })

        self.assertEqual(result.preferred_name, "")
        self.assertEqual(result.email, "recruiting@example.org")
        self.assertEqual(result.source, NameSource.UNKNOWN)
        self.assertEqual(result.confidence, NameConfidence.LOW)
        self.assertEqual(result.status, NameStatus.NEEDS_REVIEW)


class SourceProviderAdapterTests(SimpleTestCase):
    def test_manual_adapter_normalizes_gmail_shaped_messages(self):
        adapter = get_source_provider_adapter("manual_v1")
        messages = adapter.fetch_latest_messages(
            None,
            payload={
                "messages": [
                    {
                        "id": "msg-1",
                        "thread_id": "thread-1",
                        "from": "Vaughn Smith <vaughn@example.com>",
                        "date": "2026-09-01T16:00:00Z",
                        "subject": "Senior Django Engineer",
                    }
                ]
            },
        )

        self.assertEqual(messages, [
            SourceMessage(
                provider_message_id="msg-1",
                provider_thread_id="thread-1",
                from_header="Vaughn Smith <vaughn@example.com>",
                sent_at="2026-09-01T16:00:00Z",
                subject="Senior Django Engineer",
            )
        ])


class SourceImportAuditTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sourcework-user", email="sourcework@example.com", password="pass")
        user_ct = ContentType.objects.get_for_model(User)
        self.group = Group.objects.create(
            title="Sourcework Group",
            slug="sourcework-group",
            description="Test group",
            group_type="community",
            decorators=[],
            additional_permissions=[],
            sponsor_content_type=user_ct,
            sponsor_object_id=self.user.id,
        )
        self.connection = ExternalConnection.objects.create(
            group=self.group,
            owner=self.user,
            provider="google_gmail",
            provider_account_id="sourcework@example.com",
            display_name="Google Mail",
            provider_scopes=["gmail.readonly"],
            status=ExternalConnectionStatus.READY,
        )
        self.grant = SourceGrant.objects.create(
            connection=self.connection,
            resource_kind="gmail_label",
            resource_id="Recruiters",
            display_name="Recruiters",
            capabilities=["read"],
            created_by=self.user,
        )

    def test_import_latest_from_source_grant_creates_working_set_and_action_run(self):
        result = import_latest_from_source_grant(
            self.grant,
            user=self.user,
            payload={
                "messages": [
                    {
                        "provider_message_id": "msg-1",
                        "provider_thread_id": "thread-1",
                        "from_header": "Vaughn Smith <vaughn@example.com>",
                        "sent_at": "2026-09-01T16:00:00Z",
                        "subject": "Senior Django Engineer",
                        "body": "Best regards,\nSomeone Else",
                    }
                ]
            },
        )

        self.assertEqual(result["adapter"], "manual_v1")
        self.assertEqual(result["messages_seen"], 1)
        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["provisional_created"], 1)

        thing = ProvisionalThing.objects.get(group=self.group, email="vaughn@example.com")
        self.assertEqual(thing.preferred_name, "Vaughn Smith")
        self.assertEqual(thing.name_source, NameSource.HEADER)

        working_set = WorkingSet.objects.get(group=self.group, title="Recruiter Reconnection")
        self.assertEqual(working_set.summary["total"], 1)
        self.assertEqual(working_set.summary["ready"], 1)

        action_run = ActionRun.objects.get(id=result["action_run_id"])
        self.assertEqual(action_run.status, ActionRunStatus.SUCCEEDED)
        self.assertEqual(action_run.source_grant, self.grant)
        self.assertEqual(action_run.result_payload["messages_seen"], 1)

    def test_switchboard_denies_request_outside_source_grant_before_provider_access(self):
        with self.assertRaises(SourceGrantAccessError) as exc:
            fetch_latest_messages_for_source_grant(
                SourceGrantReadRequest(
                    grant_id=str(self.grant.id),
                    resource_kind="gmail_label",
                    resource_id="Different Label",
                    limit=5,
                ),
                user=self.user,
            )

        self.assertEqual(exc.exception.code, "resource_id_denied")

    def test_switchboard_latest_messages_endpoint_requires_internal_service_scope(self):
        response = APIClient().post(
            f"/api/switchboard/source-grants/{self.grant.id}/messages/latest",
            {
                "resource_kind": "gmail_label",
                "resource_id": "Recruiters",
                "limit": 5,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "service_scope_required")
