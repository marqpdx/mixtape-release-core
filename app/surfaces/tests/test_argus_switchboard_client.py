from unittest.mock import MagicMock, patch

import jwt
import requests
from django.test import SimpleTestCase, override_settings

from surfaces.services.argus_switchboard_client import (
    ArgusSwitchboardError,
    NotReachable,
    list_blocks,
    start_run,
)

SECRET = "test-argus-run-secret-at-least-32-bytes-long"
OTHER_SECRET = "test-general-service-secret-at-least-32-bytes-long"


def _ok_response(body):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = body
    return response


def _error_response(status_code, text=""):
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    return response


@override_settings(ARGUS_SWITCHBOARD_URL="https://cass.example/switchboard", ARGUS_RUN_JWT_SECRET=SECRET)
class ArgusSwitchboardClientTests(SimpleTestCase):
    def test_start_run_happy_path_sends_bearer_token_signed_with_argus_run_secret(self):
        with patch("surfaces.services.argus_switchboard_client.requests.post") as mock_post:
            mock_post.return_value = _ok_response({"status": "started", "tool": "argus.start_run"})
            result = start_run(block_slug="help-fidelity-01", actor_user_id="u-1")

        self.assertEqual(result, {"status": "started", "tool": "argus.start_run"})

        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["json"]["payload"]["block_slug"], "help-fidelity-01")
        self.assertEqual(kwargs["json"]["actor"], {"user_id": "u-1"})

        auth_header = kwargs["headers"]["Authorization"]
        self.assertTrue(auth_header.startswith("Bearer "))
        token = auth_header[len("Bearer "):]
        payload = jwt.decode(
            token, SECRET, algorithms=["HS256"], issuer="crossroads-core", audience="cass-switchboard-argus",
        )
        self.assertEqual(payload["sub"], "core")

        # The token must not verify against the general service secret --
        # it's a narrowly-scoped secret, not a copy of SERVICE_JWT_SECRET.
        with self.assertRaises(jwt.PyJWTError):
            jwt.decode(
                token, OTHER_SECRET, algorithms=["HS256"], issuer="crossroads-core", audience="cass-switchboard-argus",
            )

    def test_list_blocks_sends_tenant_payload(self):
        with patch("surfaces.services.argus_switchboard_client.requests.post") as mock_post:
            mock_post.return_value = _ok_response({"status": "ok", "available": True, "blocks": []})
            result = list_blocks()

        self.assertEqual(result, {"status": "ok", "available": True, "blocks": []})
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["json"]["tenant"]["namespace"], "platform:crossroads")
        self.assertIn("id", kwargs["json"]["tenant"])

    def test_timeout_is_not_reachable(self):
        with patch("surfaces.services.argus_switchboard_client.requests.post") as mock_post:
            mock_post.side_effect = requests.exceptions.ReadTimeout("slow")
            result = start_run(block_slug="help-fidelity-01")
        self.assertIsInstance(result, NotReachable)

    def test_connection_error_is_not_reachable(self):
        with patch("surfaces.services.argus_switchboard_client.requests.post") as mock_post:
            mock_post.side_effect = requests.exceptions.ConnectionError("down")
            result = start_run(block_slug="help-fidelity-01")
        self.assertIsInstance(result, NotReachable)

    def test_5xx_is_not_reachable(self):
        with patch("surfaces.services.argus_switchboard_client.requests.post") as mock_post:
            mock_post.return_value = _error_response(503, "unavailable")
            result = start_run(block_slug="help-fidelity-01")
        self.assertIsInstance(result, NotReachable)

    def test_401_is_not_reachable(self):
        with patch("surfaces.services.argus_switchboard_client.requests.post") as mock_post:
            mock_post.return_value = _error_response(401, "invalid token")
            result = start_run(block_slug="help-fidelity-01")
        self.assertIsInstance(result, NotReachable)

    def test_403_is_not_reachable(self):
        with patch("surfaces.services.argus_switchboard_client.requests.post") as mock_post:
            mock_post.return_value = _error_response(403, "forbidden")
            result = start_run(block_slug="help-fidelity-01")
        self.assertIsInstance(result, NotReachable)

    def test_validation_4xx_raises_client_error_not_not_reachable(self):
        with patch("surfaces.services.argus_switchboard_client.requests.post") as mock_post:
            mock_post.return_value = _error_response(422, "bad payload")
            with self.assertRaises(ArgusSwitchboardError) as exc_info:
                start_run(block_slug="")
        self.assertEqual(exc_info.exception.status_code, 422)

    @override_settings(ARGUS_SWITCHBOARD_URL=None)
    def test_unset_url_is_not_reachable_without_sending_a_request(self):
        with patch("surfaces.services.argus_switchboard_client.requests.post") as mock_post:
            result = start_run(block_slug="help-fidelity-01")

        mock_post.assert_not_called()
        self.assertIsInstance(result, NotReachable)

    @override_settings(ARGUS_RUN_JWT_SECRET=None)
    def test_unset_secret_is_not_reachable_without_sending_a_request(self):
        with patch("surfaces.services.argus_switchboard_client.requests.post") as mock_post:
            result = start_run(block_slug="help-fidelity-01")

        mock_post.assert_not_called()
        self.assertIsInstance(result, NotReachable)
