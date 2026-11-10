"""handoff-2026-11-10-blue-inkwell-one-minter.md: agent_parse and
agent_research used to sign Inkwell calls with SERVICE_JWT_SECRET through
their own local minters -- a different secret than Inkwell verifies
against (INKWELL_SERVICE_JWT_SECRET), so every real call got a 401. Both
now call inkwell.client's shared minter instead."""

from unittest.mock import MagicMock, patch

import jwt
from django.test import SimpleTestCase, override_settings

from initiatives.services.agent_parse import AgentParseError, parse_agent_command
from initiatives.services.agent_research import AgentResearchError, summarize_via_inkwell

INKWELL_SECRET = "test-inkwell-service-secret-at-least-32-bytes-long"
SERVICE_SECRET = "test-general-service-secret-at-least-32-bytes-long"


def _ok_response(body):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = body
    return response


@override_settings(INKWELL_SERVICE_JWT_SECRET=INKWELL_SECRET, SERVICE_JWT_SECRET=SERVICE_SECRET)
class AgentParseInkwellTokenTests(SimpleTestCase):
    def test_sends_a_token_signed_with_inkwell_service_jwt_secret(self):
        with patch("initiatives.services.agent_parse.requests.post") as mock_post:
            mock_post.return_value = _ok_response({"ok": True})
            parse_agent_command(
                text="do a thing", capture_mode="note", source="console",
                initiative_id=None, sponsor_model=None, sponsor_id=None,
                principal_user_id=None,
            )

        token = mock_post.call_args.kwargs["headers"]["X-Service-Token"]
        payload = jwt.decode(
            token, INKWELL_SECRET, algorithms=["HS256"], issuer="mixtape", audience="django-inkwell",
        )
        self.assertEqual(payload["sub"], "switchboard")

        with self.assertRaises(jwt.PyJWTError):
            jwt.decode(
                token, SERVICE_SECRET, algorithms=["HS256"], issuer="mixtape", audience="django-inkwell",
            )

    @override_settings(INKWELL_SERVICE_JWT_SECRET=None)
    def test_unconfigured_inkwell_secret_raises_without_sending_a_request(self):
        with patch("initiatives.services.agent_parse.requests.post") as mock_post:
            with self.assertRaises(AgentParseError) as exc_info:
                parse_agent_command(
                    text="do a thing", capture_mode="note", source="console",
                    initiative_id=None, sponsor_model=None, sponsor_id=None,
                    principal_user_id=None,
                )

        mock_post.assert_not_called()
        self.assertEqual(exc_info.exception.status_code, 503)


@override_settings(INKWELL_SERVICE_JWT_SECRET=INKWELL_SECRET, SERVICE_JWT_SECRET=SERVICE_SECRET)
class AgentResearchInkwellTokenTests(SimpleTestCase):
    def test_summarize_sends_a_token_signed_with_inkwell_service_jwt_secret(self):
        with patch("initiatives.services.agent_research.requests.post") as mock_post:
            mock_post.return_value = _ok_response({"summary": "ok"})
            summarize_via_inkwell(text="some text")

        token = mock_post.call_args.kwargs["headers"]["X-Service-Token"]
        payload = jwt.decode(
            token, INKWELL_SECRET, algorithms=["HS256"], issuer="mixtape", audience="django-inkwell",
        )
        self.assertEqual(payload["sub"], "switchboard")

        with self.assertRaises(jwt.PyJWTError):
            jwt.decode(
                token, SERVICE_SECRET, algorithms=["HS256"], issuer="mixtape", audience="django-inkwell",
            )

    @override_settings(INKWELL_SERVICE_JWT_SECRET=None)
    def test_unconfigured_inkwell_secret_raises_without_sending_a_request(self):
        with patch("initiatives.services.agent_research.requests.post") as mock_post:
            with self.assertRaises(AgentResearchError) as exc_info:
                summarize_via_inkwell(text="some text")

        mock_post.assert_not_called()
        self.assertEqual(exc_info.exception.status_code, 503)
