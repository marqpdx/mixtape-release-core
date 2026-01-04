import time
import jwt

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase


User = get_user_model()


def mint_service_jwt(*, sub: str, aud: str = "django-ir", scope: str = "stackroom.ir.write") -> str:
    now = int(time.time())
    payload = {
        "iss": getattr(settings, "SERVICE_JWT_ISS", "mixtape"),
        "aud": aud,
        "sub": str(sub),
        "iat": now,
        "nbf": now,
        "exp": now + 600,
        "svc": "stackroom",
        "scope": scope,
    }
    return jwt.encode(payload, settings.SERVICE_JWT_SECRET, algorithm=getattr(settings, "SERVICE_JWT_ALG", "HS256"))


class TestStackroomServiceAuth(APITestCase):
    @classmethod
    def setUpTestData(cls):
        # Make sure the service user exists (pk should match your real strategy)
        cls.service_user = User.objects.create_user(
            username="stackroom_service",
            password=None,
        )

    def test_service_jwt_allows_stackroom_scope(self):
        token = mint_service_jwt(sub=self.service_user.pk, scope="stackroom.ir.write")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        # Pick a cheap endpoint you’ll have (health/ping). If you don’t have it yet,
        # add GET /api/stackroom/ping -> 200.
        resp = self.client.get("/api/stackroom/ping")
        self.assertIn(resp.status_code, (200, 204))

    def test_service_jwt_rejected_if_scope_wrong(self):
        token = mint_service_jwt(sub=self.service_user.pk, scope="something.else")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        resp = self.client.get("/api/stackroom/ping")
        # Expect 403 if you add HasStackroomIRScope, otherwise it may pass.
        # Make it 403 once the permission is installed.
        self.assertIn(resp.status_code, (401, 403))

    def test_invalid_audience_rejected(self):
        token = mint_service_jwt(sub=self.service_user.pk, aud="wrong-aud")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        resp = self.client.get("/api/stackroom/ping")
        self.assertIn(resp.status_code, (401, 403))
