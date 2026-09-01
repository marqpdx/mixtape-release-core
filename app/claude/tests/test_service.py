"""
Smoke tests for claude.service.

run_blocking: uses unittest.mock to avoid subprocess in CI.
stream:       integration test — requires `claude` binary on PATH.
              Run manually: pytest app/claude/tests/test_service.py -k streaming -s
"""

from __future__ import annotations

import os
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from claude import service as claude_service


class TestRunBlocking(unittest.TestCase):
    def test_returns_stdout_on_success(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "  hello world  "
        mock_result.stderr = ""
        with patch("claude.service.subprocess.run", return_value=mock_result) as mock_run:
            result = claude_service.run_blocking("say hello", cwd="/tmp", timeout=30)
        self.assertEqual(result.output, "hello world")
        self.assertIsNone(result.failure)
        args, kwargs = mock_run.call_args
        self.assertIn("-p", args[0])
        self.assertIn("--dangerously-skip-permissions", args[0])
        self.assertEqual(kwargs["input"], "say hello")
        self.assertEqual(kwargs["timeout"], 30)

    def test_unwraps_json_output_and_records_usage(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = (
            '{"result":"hello world","usage":{"input_tokens":12,"output_tokens":3},'
            '"duration_ms":456}'
        )
        mock_result.stderr = ""
        with patch("claude.service.subprocess.run", return_value=mock_result) as mock_run:
            result = claude_service.run_blocking(
                "say hello",
                cwd="/tmp",
                log_context={"phase": "test"},
            )
        self.assertEqual(result.output, "hello world")
        self.assertEqual(result.usage, {"input_tokens": 12, "output_tokens": 3})
        self.assertEqual(result.elapsed_ms, 456)
        args, _ = mock_run.call_args
        self.assertIn("--output-format", args[0])
        self.assertIn("json", args[0])

    def test_returns_error_on_nonzero_exit(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "error"
        with patch("claude.service.subprocess.run", return_value=mock_result):
            result = claude_service.run_blocking("say hello", cwd="/tmp")
        self.assertIsNone(result.output)
        self.assertEqual(result.failure, "error")

    def test_returns_auth_failure_on_not_logged_in(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "Not logged in. Please run /login"
        mock_result.stderr = ""
        with patch("claude.service.subprocess.run", return_value=mock_result):
            result = claude_service.run_blocking("say hello", cwd="/tmp")
        self.assertIsNone(result.output)
        self.assertEqual(result.failure, "auth_failure")

    def test_returns_timeout_on_timeout(self):
        with patch("claude.service.subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 90)):
            result = claude_service.run_blocking("say hello", cwd="/tmp")
        self.assertIsNone(result.output)
        self.assertEqual(result.failure, "timeout")

    def test_returns_empty_on_empty_stdout(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "   "
        with patch("claude.service.subprocess.run", return_value=mock_result):
            result = claude_service.run_blocking("say hello", cwd="/tmp")
        self.assertIsNone(result.output)
        self.assertEqual(result.failure, "empty")

    def test_run_as_user_prepends_runuser(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "ok"
        mock_result.stderr = ""
        with patch("claude.service.subprocess.run", return_value=mock_result) as mock_run:
            result = claude_service.run_blocking("say ok", cwd="/tmp", run_as_user="tob-catalyst")
        self.assertEqual(result.output, "ok")
        args, _ = mock_run.call_args
        self.assertEqual(args[0][0], "runuser")
        self.assertIn("-u", args[0])
        self.assertIn("tob-catalyst", args[0])


class TestStream(unittest.TestCase):
    """
    Integration smoke test — skip unless `claude` binary is on PATH.
    Run manually: pytest app/claude/tests/test_service.py -k streaming -s
    """

    @unittest.skipUnless(
        __import__("shutil").which("claude") is not None,
        "claude binary not found on PATH",
    )
    def test_streaming_yields_tokens(self):
        prompt = "Reply with exactly the word: PONG"
        chunks = list(claude_service.stream(prompt, cwd="/tmp"))
        full = "".join(chunks).strip()
        self.assertTrue(len(full) > 0, "stream yielded no output")
        self.assertIn("PONG", full, f"expected PONG in output, got: {full!r}")


class TestStreamJsonSession(unittest.TestCase):
    def test_read_turn_times_out_and_kills_process(self):
        read_fd, write_fd = os.pipe()
        proc = MagicMock()
        proc.stdout = os.fdopen(read_fd, "r", encoding="utf-8")
        proc.kill = MagicMock()

        try:
            events = list(claude_service._read_turn(proc, "session-timeout-test", timeout=0.01))
        finally:
            os.close(write_fd)
            proc.stdout.close()

        self.assertEqual(events, [("error", "Claude Code timed out after 0.01s.")])
        proc.kill.assert_called_once()
