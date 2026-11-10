import jwt
from django.test import SimpleTestCase, override_settings

from inkwell.client import InkwellUnavailableError, _mint_inkwell_service_token

SECRET = "test-inkwell-service-secret-at-least-32-bytes-long"


@override_settings(INKWELL_SERVICE_JWT_SECRET=SECRET)
class MintInkwellServiceTokenTests(SimpleTestCase):
    """ST-9 (zz/spike-jwt-and-token-practices.md T1/F3, 2026-11-10): one
    minter for every core -> Inkwell /service/* call, signed with
    INKWELL_SERVICE_JWT_SECRET, never SERVICE_JWT_SECRET."""

    def test_default_subject_is_django(self):
        token = _mint_inkwell_service_token()
        payload = jwt.decode(
            token, SECRET, algorithms=["HS256"], issuer="mixtape", audience="django-inkwell",
        )
        self.assertEqual(payload["sub"], "django")

    def test_subject_override_is_honored(self):
        token = _mint_inkwell_service_token(subject="switchboard")
        payload = jwt.decode(
            token, SECRET, algorithms=["HS256"], issuer="mixtape", audience="django-inkwell",
        )
        self.assertEqual(payload["sub"], "switchboard")

    @override_settings(INKWELL_SERVICE_JWT_SECRET=None)
    def test_unconfigured_secret_raises(self):
        with self.assertRaises(InkwellUnavailableError):
            _mint_inkwell_service_token()

    def test_a_different_secret_does_not_verify(self):
        """A token minted here must not verify against some other
        secret -- confirms this minter isn't accidentally reachable by
        SERVICE_JWT_SECRET-style verification elsewhere."""
        token = _mint_inkwell_service_token()
        with self.assertRaises(jwt.PyJWTError):
            jwt.decode(
                token, "a-different-secret-entirely-at-least-32-bytes",
                algorithms=["HS256"], issuer="mixtape", audience="django-inkwell",
            )
