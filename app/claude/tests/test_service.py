"""
Smoke tests for claude.service.

run_blocking: uses unittest.mock to avoid subprocess in CI.
stream:       integration test — requires `claude` binary on PATH.
              Run manually: pytest app/claude/tests/test_service.py -k streaming -s
"""

from __future__ import annotations

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
        self.assertEqual(result, "hello world")
        args, kwargs = mock_run.call_args
        self.assertIn("-p", args[0])
        self.assertIn("--dangerously-skip-permissions", args[0])
        self.assertEqual(kwargs["input"], "say hello")
        self.assertEqual(kwargs["timeout"], 30)

    def test_returns_none_on_nonzero_exit(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error"
        with patch("claude.service.subprocess.run", return_value=mock_result):
            result = claude_service.run_blocking("say hello", cwd="/tmp")
        self.assertIsNone(result)

    def test_returns_none_on_timeout(self):
        with patch("claude.service.subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 90)):
            result = claude_service.run_blocking("say hello", cwd="/tmp")
        self.assertIsNone(result)

    def test_returns_none_on_empty_stdout(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "   "
        with patch("claude.service.subprocess.run", return_value=mock_result):
            result = claude_service.run_blocking("say hello", cwd="/tmp")
        self.assertIsNone(result)


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
