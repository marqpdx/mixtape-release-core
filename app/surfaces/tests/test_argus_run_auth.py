import jwt
from django.test import SimpleTestCase, override_settings

from surfaces.services.argus_run_auth import ArgusRunAuthError, mint_argus_run_token


class MintArgusRunTokenTests(SimpleTestCase):
    @override_settings(ARGUS_RUN_JWT_SECRET="")
    def test_raises_when_secret_unconfigured(self) -> None:
        with self.assertRaises(ArgusRunAuthError):
            mint_argus_run_token()

    @override_settings(
        ARGUS_RUN_JWT_SECRET="test-argus-run-secret-at-least-32-bytes-long",
        ARGUS_RUN_JWT_ISS="crossroads-core",
        ARGUS_RUN_JWT_AUD="cass-switchboard-argus",
        ARGUS_RUN_JWT_TTL_SECONDS=120,
    )
    def test_produces_a_token_verifiable_with_the_same_claims(self) -> None:
        token = mint_argus_run_token(subject="core")

        payload = jwt.decode(
            token,
            "test-argus-run-secret-at-least-32-bytes-long",
            algorithms=["HS256"],
            issuer="crossroads-core",
            audience="cass-switchboard-argus",
            options={"require": ["exp", "iat", "nbf", "iss", "aud", "sub"]},
        )
        self.assertEqual(payload["sub"], "core")

    @override_settings(
        ARGUS_RUN_JWT_SECRET="test-argus-run-secret-at-least-32-bytes-long",
        ARGUS_RUN_JWT_AUD="cass-switchboard-argus",
    )
    def test_rejects_verification_with_a_different_audience(self) -> None:
        token = mint_argus_run_token()

        with self.assertRaises(jwt.InvalidAudienceError):
            jwt.decode(
                token,
                "test-argus-run-secret-at-least-32-bytes-long",
                algorithms=["HS256"],
                audience="some-other-audience",
                options={"require": ["exp", "iat", "nbf", "iss", "aud", "sub"]},
            )
