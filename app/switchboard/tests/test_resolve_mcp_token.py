import time
from unittest.mock import patch

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from tenant_runtime import pool
from tenant_runtime.models import McpRuntimeToken, TenantClaudeRuntime
from tenant_runtime.resolve import ensure_person_runtime

User = get_user_model()


def _service_token(scopes):
    now = int(time.time())
    claims = {
        "sub": "switchboard",
        "scopes": list(scopes),
        "iat": now,
        "nbf": now - 5,
        "exp": now + 600,
        "iss": "mixtape",
        "aud": "django-api",
    }
    return jwt.encode(claims, settings.SERVICE_JWT_SECRET, algorithm="HS256")


def _patch_pool(members):
    return [
        patch.object(pool, "pool_members", return_value=members),
        patch.object(pool, "_groups_of", return_value={"mixtape-runtimes"}),
        patch.object(pool, "home_of", side_effect=lambda n: f"/home/{n}"),
    ]


@override_settings(SERVICE_JWT_SECRET="resolve-mcp-token-test-secret")
class ResolveMcpTokenTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.patches = _patch_pool(["mxr-1"])
        for p in self.patches:
            p.start()
        self.user = User.objects.create_user(username="resolve_mcp_user", password="testpass123")
        runtime = ensure_person_runtime(self.user)
        runtime.status = TenantClaudeRuntime.STATUS_READY
        runtime.save(update_fields=["status"])
        self.token, self.raw_token = McpRuntimeToken.issue(person=self.user, runtime=runtime)

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _post(self, body, scopes=("mcp:resolve",)):
        token = _service_token(scopes)
        return self.client.post(
            "/api/switchboard/resolve-mcp-token",
            data=body,
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    def test_resolves_a_valid_token(self):
        response = self._post({"token": self.raw_token})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["valid"])
        self.assertEqual(data["person_id"], str(self.user.pk))
        self.assertIsNone(data["group_id"])
        self.assertEqual(data["scopes"], ["read"])

    def test_resolving_updates_last_used_at(self):
        self.assertIsNone(self.token.last_used_at)
        self._post({"token": self.raw_token})
        self.token.refresh_from_db()
        self.assertIsNotNone(self.token.last_used_at)

    def test_unknown_token_is_a_200_not_valid(self):
        response = self._post({"token": "mcp_not-a-real-token"})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["valid"])

    def test_revoked_token_is_a_200_not_valid(self):
        self.token.revoke()

        response = self._post({"token": self.raw_token})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["valid"])

    def test_missing_token_field_is_400(self):
        response = self._post({})
        self.assertEqual(response.status_code, 400)

    def test_rejects_request_without_required_scope(self):
        response = self._post({"token": self.raw_token}, scopes=("some:other:scope",))
        self.assertEqual(response.status_code, 403)
