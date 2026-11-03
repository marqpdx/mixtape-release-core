import time

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

User = get_user_model()

_DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
_DEFAULT_TENANT_NAMESPACE = "platform:crossroads"


def _service_token(scopes: list[str]) -> str:
    now = int(time.time())
    claims = {
        "sub": "switchboard",
        "scopes": scopes,
        "iat": now,
        "nbf": now - 5,
        "exp": now + 600,
        "iss": "mixtape",
        "aud": "django-api",
    }
    return jwt.encode(claims, settings.SERVICE_JWT_SECRET, algorithm="HS256")


@override_settings(SERVICE_JWT_SECRET="authorize-tool-request-test-secret")
class AuthorizeToolRequestTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="authz_user", password="testpass123")

    def _post(self, body, scopes=("authorization:read",)):
        token = _service_token(list(scopes))
        return self.client.post(
            "/api/switchboard/authorize",
            data=body,
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    def test_allows_known_tenant_and_user(self):
        response = self._post(
            {
                "tenant": {"id": _DEFAULT_TENANT_ID, "namespace": _DEFAULT_TENANT_NAMESPACE},
                "actor": {"user_id": str(self.user.pk)},
            }
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["allowed"])
        self.assertEqual(data["principal"]["user_id"], str(self.user.pk))
        self.assertIsNone(data["reason"])

    def test_allows_known_tenant_with_service_principal(self):
        response = self._post(
            {
                "tenant": {"id": _DEFAULT_TENANT_ID, "namespace": _DEFAULT_TENANT_NAMESPACE},
                "actor": {"service_token_id": "svc_demo"},
            }
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["allowed"])
        self.assertEqual(data["principal"]["service_token_id"], "svc_demo")

    def test_denies_unknown_tenant(self):
        response = self._post(
            {
                "tenant": {"id": "11111111-1111-1111-1111-111111111111", "namespace": "tenant:other"},
                "actor": {"user_id": str(self.user.pk)},
            }
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["allowed"])
        self.assertEqual(data["reason"], "unknown_tenant")

    def test_denies_mismatched_namespace_for_known_tenant_id(self):
        response = self._post(
            {
                "tenant": {"id": _DEFAULT_TENANT_ID, "namespace": "tenant:other"},
                "actor": {"user_id": str(self.user.pk)},
            }
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["allowed"])
        self.assertEqual(response.json()["reason"], "unknown_tenant")

    def test_denies_unknown_user(self):
        response = self._post(
            {
                "tenant": {"id": _DEFAULT_TENANT_ID, "namespace": _DEFAULT_TENANT_NAMESPACE},
                "actor": {"user_id": "99999999-9999-9999-9999-999999999999"},
            }
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["allowed"])
        self.assertEqual(data["reason"], "unknown_user")

    def test_denies_missing_actor(self):
        response = self._post(
            {"tenant": {"id": _DEFAULT_TENANT_ID, "namespace": _DEFAULT_TENANT_NAMESPACE}}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["allowed"])
        self.assertEqual(data["reason"], "actor_required")

    def test_rejects_missing_tenant_fields(self):
        response = self._post({"actor": {"user_id": str(self.user.pk)}})

        self.assertEqual(response.status_code, 400)

    def test_rejects_request_without_required_scope(self):
        response = self._post(
            {
                "tenant": {"id": _DEFAULT_TENANT_ID, "namespace": _DEFAULT_TENANT_NAMESPACE},
                "actor": {"user_id": str(self.user.pk)},
            },
            scopes=("some:other:scope",),
        )

        self.assertEqual(response.status_code, 403)

    def test_rejects_unauthenticated_request(self):
        response = self.client.post(
            "/api/switchboard/authorize",
            data={
                "tenant": {"id": _DEFAULT_TENANT_ID, "namespace": _DEFAULT_TENANT_NAMESPACE},
                "actor": {"user_id": str(self.user.pk)},
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)
