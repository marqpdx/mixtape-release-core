from __future__ import annotations

import json
import os
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from codex import service as codex_service


class TestCodexJsonlParser(unittest.TestCase):
    def test_parses_thread_message_and_usage(self):
        stdout = "\n".join(
            [
                json.dumps({"type": "thread.started", "thread_id": "thread-123"}),
                json.dumps({"type": "turn.started"}),
                json.dumps({
                    "type": "item.completed",
                    "item": {"id": "item-1", "type": "agent_message", "text": "hello"},
                }),
                json.dumps({
                    "type": "turn.completed",
                    "usage": {"input_tokens": 10, "output_tokens": 2},
                }),
            ]
        )

        result = codex_service.parse_jsonl_events(stdout)

        self.assertEqual(result.output, "hello")
        self.assertEqual(result.provider_session_id, "thread-123")
        self.assertEqual(result.usage, {"input_tokens": 10, "output_tokens": 2})
        self.assertIsNone(result.failure)

    def test_classifies_auth_failure(self):
        stdout = json.dumps({
            "type": "error",
            "message": "Not logged in. Run codex login.",
        })

        result = codex_service.parse_jsonl_events(stdout)

        self.assertEqual(result.failure, "auth_failure")


class TestCodexRunBlocking(unittest.TestCase):
    def test_run_blocking_uses_json_read_only_stdin_and_strips_openai_env(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "\n".join(
            [
                json.dumps({"type": "thread.started", "thread_id": "thread-123"}),
                json.dumps({
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "ok"},
                }),
                json.dumps({"type": "turn.completed"}),
            ]
        )
        mock_result.stderr = ""

        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret"}, clear=False):
            with patch("codex.service.subprocess.run", return_value=mock_result) as mock_run:
                result = codex_service.run_blocking(
                    "say ok",
                    cwd="/tmp",
                    timeout=30,
                    run_as_user="tenant-a",
                    home_dir="/home/tenant-a",
                )

        self.assertEqual(result.output, "ok")
        args, kwargs = mock_run.call_args
        self.assertEqual(args[0][:4], ["runuser", "-u", "tenant-a", "--"])
        self.assertIn("exec", args[0])
        self.assertIn("--json", args[0])
        self.assertIn("--sandbox", args[0])
        self.assertIn("read-only", args[0])
        self.assertIn("--skip-git-repo-check", args[0])
        self.assertEqual(args[0][-1], "-")
        self.assertEqual(kwargs["input"], "say ok")
        self.assertEqual(kwargs["env"]["HOME"], "/home/tenant-a")
        self.assertEqual(kwargs["env"]["CODEX_HOME"], "/home/tenant-a/.codex")
        self.assertNotIn("OPENAI_API_KEY", kwargs["env"])

    def test_resume_blocking_uses_provider_session_id(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "\n".join(
            [
                json.dumps({
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "continued"},
                }),
                json.dumps({"type": "turn.completed"}),
            ]
        )
        mock_result.stderr = ""

        with patch("codex.service.subprocess.run", return_value=mock_result) as mock_run:
            result = codex_service.resume_blocking(
                "thread-123",
                "continue",
                cwd="/tmp",
                run_as_user="tenant-a",
                home_dir="/home/tenant-a",
            )

        self.assertEqual(result.output, "continued")
        args, _ = mock_run.call_args
        self.assertIn("resume", args[0])
        self.assertIn("thread-123", args[0])
        self.assertNotIn("--sandbox", args[0])
        self.assertNotIn("--cd", args[0])

    def test_returns_timeout_on_timeout(self):
        with patch(
            "codex.service.subprocess.run",
            side_effect=subprocess.TimeoutExpired("codex", 30),
        ):
            result = codex_service.run_blocking("say ok", cwd="/tmp", timeout=30)

        self.assertIsNone(result.output)
        self.assertEqual(result.failure, "timeout")
