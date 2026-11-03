"""McpRuntimeToken and the /api/me/mcp-tokens/ routes (Service Trust ST-3, SW-11.6)."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from groups.models import Group, GroupMembership
from tenant_runtime import pool
from tenant_runtime.models import McpRuntimeToken, TenantClaudeRuntime
from tenant_runtime.resolve import ensure_person_runtime

User = get_user_model()


def _user(name):
    return User.objects.create_user(username=name, email=f"{name}@example.com", password="x")


def _patch_pool(members):
    return [
        patch.object(pool, "pool_members", return_value=members),
        patch.object(pool, "_groups_of", return_value={"mixtape-runtimes"}),
        patch.object(pool, "home_of", side_effect=lambda n: f"/home/{n}"),
    ]


def _ready_runtime(user):
    runtime = ensure_person_runtime(user)
    runtime.status = TenantClaudeRuntime.STATUS_READY
    runtime.save(update_fields=["status"])
    return runtime


def _group(sponsor, title="Test Group", slug="test-group"):
    group = Group(
        title=title,
        slug=slug,
        description="Test group",
        group_type="community",
        decorators=[],
        additional_permissions=[],
    )
    group.set_sponsor(sponsor)
    group.set_submitted_by(sponsor)
    group.author = sponsor
    group.author_name = sponsor.get_full_name() or sponsor.username
    group.save()
    return group


def _add_member(group, user, roles=None):
    user_ct = ContentType.objects.get_for_model(User)
    return GroupMembership.objects.create(
        group=group,
        member_content_type=user_ct,
        member_object_id=user.id,
        roles=roles or ["member"],
        is_active=True,
        is_pending=False,
    )


class McpRuntimeTokenModelTests(TestCase):
    def setUp(self):
        self.patches = _patch_pool(["mxr-1", "mxr-2"])
        for p in self.patches:
            p.start()
        self.alice = _user("alice-mcp")

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_issue_returns_raw_token_once_and_stores_only_its_hash(self):
        runtime = _ready_runtime(self.alice)
        token, raw = McpRuntimeToken.issue(person=self.alice, runtime=runtime)

        self.assertTrue(raw.startswith("mcp_"))
        self.assertNotEqual(token.token_hash, raw)
        self.assertEqual(token.token_prefix, raw[:12])
        self.assertEqual(token.scopes, ["read"])
        self.assertTrue(token.is_valid)

    def test_resolve_finds_the_matching_valid_token(self):
        runtime = _ready_runtime(self.alice)
        token, raw = McpRuntimeToken.issue(person=self.alice, runtime=runtime)

        resolved = McpRuntimeToken.resolve(raw)
        self.assertEqual(resolved.pk, token.pk)
        self.assertIsNone(McpRuntimeToken.resolve("mcp_not-a-real-token"))

    def test_revoked_token_is_invalid_and_no_longer_resolves(self):
        runtime = _ready_runtime(self.alice)
        token, raw = McpRuntimeToken.issue(person=self.alice, runtime=runtime)

        token.revoke()

        self.assertFalse(token.is_valid)
        self.assertIsNone(McpRuntimeToken.resolve(raw))

    def test_expired_token_is_invalid(self):
        runtime = _ready_runtime(self.alice)
        token, _raw = McpRuntimeToken.issue(person=self.alice, runtime=runtime)
        token.expires_at = timezone.now() - timezone.timedelta(seconds=1)
        token.save(update_fields=["expires_at"])

        self.assertFalse(token.is_valid)


class MyMcpTokensApiTests(TestCase):
    def setUp(self):
        self.patches = _patch_pool(["mxr-1", "mxr-2"])
        for p in self.patches:
            p.start()
        self.alice = _user("alice-mcp-api")
        self.bob = _user("bob-mcp-api")
        self.client = APIClient()
        self.client.force_authenticate(self.alice)

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_mint_requires_a_ready_runtime(self):
        response = self.client.post("/api/me/mcp-tokens/")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_mint_returns_raw_token_once(self):
        _ready_runtime(self.alice)

        response = self.client.post("/api/me/mcp-tokens/")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertTrue(data["token"].startswith("mcp_"))
        self.assertIsNone(data["group_id"])
        self.assertEqual(McpRuntimeToken.objects.filter(person=self.alice).count(), 1)

    def test_mint_rejects_a_group_the_person_does_not_belong_to(self):
        _ready_runtime(self.alice)
        other_group = _group(self.bob, title="Not Alice's Group", slug="not-alices-group")

        response = self.client.post("/api/me/mcp-tokens/", {"group_id": str(other_group.id)}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_mint_accepts_a_group_the_person_belongs_to(self):
        _ready_runtime(self.alice)
        group = _group(self.alice, title="Alice's Group", slug="alices-group")
        _add_member(group, self.alice)

        response = self.client.post("/api/me/mcp-tokens/", {"group_id": str(group.id)}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["group_id"], str(group.id))

    def test_list_only_shows_your_own_tokens(self):
        runtime = _ready_runtime(self.alice)
        bob_runtime = _ready_runtime(self.bob)
        McpRuntimeToken.issue(person=self.alice, runtime=runtime)
        McpRuntimeToken.issue(person=self.bob, runtime=bob_runtime)

        response = self.client.get("/api/me/mcp-tokens/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["tokens"]), 1)

    def test_revoke_only_your_own_token(self):
        runtime = _ready_runtime(self.alice)
        bob_runtime = _ready_runtime(self.bob)
        own_token, _ = McpRuntimeToken.issue(person=self.alice, runtime=runtime)
        bobs_token, _ = McpRuntimeToken.issue(person=self.bob, runtime=bob_runtime)

        other_response = self.client.post(f"/api/me/mcp-tokens/{bobs_token.id}/revoke/")
        self.assertEqual(other_response.status_code, status.HTTP_404_NOT_FOUND)

        own_response = self.client.post(f"/api/me/mcp-tokens/{own_token.id}/revoke/")
        self.assertEqual(own_response.status_code, status.HTTP_200_OK)
        self.assertTrue(own_response.json()["revoked_at"])
        own_token.refresh_from_db()
        self.assertFalse(own_token.is_valid)
