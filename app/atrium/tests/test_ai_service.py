from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from atrium.ai import service as atrium_service
from cloud_agents.constants import (
    PROVIDER_ANTHROPIC_API,
    PROVIDER_ANTHROPIC_CLAUDE_CODE,
    PROVIDER_OPENAI_CODEX,
)


class TestAtriumAIServiceProviderDispatch(SimpleTestCase):
    def test_explicit_codex_provider_selects_codex_adapter(self):
        session = SimpleNamespace(
            sponsor_object_id=None,
            ai_provider=PROVIDER_OPENAI_CODEX,
        )

        ai = atrium_service.AtriumAIService(session=session)

        self.assertIsInstance(ai._adapter, atrium_service.CodexExecAdapter)

    def test_explicit_claude_code_provider_selects_claude_code_adapter(self):
        session = SimpleNamespace(
            sponsor_object_id=None,
            ai_provider=PROVIDER_ANTHROPIC_CLAUDE_CODE,
        )

        ai = atrium_service.AtriumAIService(session=session)

        self.assertIsInstance(ai._adapter, atrium_service.ClaudeCodeAdapter)

    @override_settings(ATRIUM_USE_CLAUDE_CODE=False)
    def test_default_provider_keeps_anthropic_api_adapter(self):
        session = SimpleNamespace(
            sponsor_object_id=None,
            ai_provider=PROVIDER_ANTHROPIC_API,
        )

        with patch.object(atrium_service, "AtriumAnthropicAdapter") as mock_adapter:
            ai = atrium_service.AtriumAIService(session=session)

        self.assertEqual(ai._adapter, mock_adapter.return_value)
