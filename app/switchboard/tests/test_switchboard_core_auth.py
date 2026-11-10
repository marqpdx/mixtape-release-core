import time

import jwt
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory

from switchboard.auth import SwitchboardCoreAuthentication

User = get_user_model()

SECRET = "test-switchboard-core-secret-at-least-32-bytes"


def _token(secret, *, scopes, sub="switchboard", kid="crossroads-switchboard", aud="switchboard-core", iss="mixtape"):
    now = int(time.time())
    claims = {
        "sub": sub,
        "scopes": list(scopes),
        "iat": now,
        "nbf": now - 5,
        "exp": now + 120,
        "iss": iss,
        "aud": aud,
    }
    headers = {"kid": kid} if kid is not None else {}
    return jwt.encode(claims, secret, algorithm="HS256", headers=headers)


def _request(token=None, *, header="HTTP_AUTHORIZATION"):
    factory = APIRequestFactory()
    kwargs = {}
    if token is not None:
        if header == "HTTP_AUTHORIZATION":
            kwargs["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        else:
            kwargs["HTTP_X_SERVICE_TOKEN"] = token
    return factory.post("/", **kwargs)


@override_settings(SWITCHBOARD_CORE_JWT_SECRETS={"crossroads-switchboard": SECRET})
class SwitchboardCoreAuthenticationTests(TestCase):
    def setUp(self):
        self.auth = SwitchboardCoreAuthentication()
        self.user = User.objects.create_user(username="su", password="x", is_superuser=True, is_staff=True)

    def test_valid_service_scope_token_returns_anonymous_with_service_principal(self):
        token = _token(SECRET, scopes=["authorization:read"])
        request = _request(token)

        user, payload = self.auth.authenticate(request)

        self.assertIsInstance(user, AnonymousUser)
        self.assertEqual(payload["scopes"], ["authorization:read"])
        self.assertEqual(request.service_principal, payload)

    def test_x_service_token_header_is_accepted(self):
        token = _token(SECRET, scopes=["mcp:resolve"])
        request = _request(token, header="X-Service-Token")

        result = self.auth.authenticate(request)

        self.assertIsNotNone(result)

    def test_concept_lookup_scope_resolves_a_real_user(self):
        token = _token(SECRET, scopes=["concept:lookup"], sub=str(self.user.pk))
        request = _request(token)

        user, payload = self.auth.authenticate(request)

        self.assertEqual(user.pk, self.user.pk)
        self.assertFalse(hasattr(request, "service_principal"))

    def test_concept_lookup_scope_with_unknown_subject_is_refused(self):
        token = _token(SECRET, scopes=["concept:lookup"], sub="00000000-0000-0000-0000-000000000000")
        request = _request(token)

        self.assertIsNone(self.auth.authenticate(request))

    @override_settings(SWITCHBOARD_CORE_JWT_SECRETS={})
    def test_no_configured_secrets_refuses(self):
        token = _token(SECRET, scopes=["authorization:read"])
        request = _request(token)

        self.assertIsNone(self.auth.authenticate(request))

    def test_unrecognized_kid_is_refused(self):
        token = _token(SECRET, scopes=["authorization:read"], kid="cass-switchboard")
        request = _request(token)

        self.assertIsNone(self.auth.authenticate(request))

    def test_missing_kid_is_refused(self):
        token = _token(SECRET, scopes=["authorization:read"], kid=None)
        request = _request(token)

        self.assertIsNone(self.auth.authenticate(request))

    def test_wrong_secret_is_refused(self):
        token = _token("a-different-secret-entirely-at-least-32-bytes", scopes=["authorization:read"])
        request = _request(token)

        self.assertIsNone(self.auth.authenticate(request))

    def test_wrong_audience_is_refused(self):
        token = _token(SECRET, scopes=["authorization:read"], aud="django-api")
        request = _request(token)

        self.assertIsNone(self.auth.authenticate(request))

    def test_no_authorization_header_returns_none(self):
        request = _request(None)
        self.assertIsNone(self.auth.authenticate(request))

    @override_settings(SERVICE_JWT_SECRET=SECRET, SERVICE_JWT_AUD="django-api")
    def test_does_not_accept_a_service_jwt_secret_token(self):
        """A token minted with the general-purpose SERVICE_JWT_SECRET must
        not pass here even if it happens to share the same raw secret value
        -- this authenticator only trusts SWITCHBOARD_CORE_JWT_SECRETS, and
        only a token whose `kid` matches one of its entries."""
        now = int(time.time())
        token = jwt.encode(
            {
                "sub": "switchboard", "scopes": ["authorization:read"],
                "iat": now, "nbf": now - 5, "exp": now + 600,
                "iss": "mixtape", "aud": "django-api",
            },
            SECRET,
            algorithm="HS256",
        )
        request = _request(token)

        self.assertIsNone(self.auth.authenticate(request))
