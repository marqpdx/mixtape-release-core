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


class TestPtyScreenReaderParsing(unittest.TestCase):
    def test_screen_reader_prompt_and_chrome_lines_are_suppressed(self):
        chrome_lines = [
            "Claude Code v2.1.240",
            "Sonnet 4.6 with medium effort · Claude Pro",
            "~/Sites/ml/active/mixtape/release/puddlejump",
            "bypass permissions on (shift+tab to cycle)",
            "effort: medium · /effort",
            "$/rc",
            "$ctrl+g to edit in Vim",
        ]
        for line in chrome_lines:
            with self.subTest(line=line):
                self.assertTrue(claude_service._is_chrome_line(line))

    def test_screen_reader_prompt_marker_is_prompt_line(self):
        self.assertTrue(claude_service._is_prompt_line("$"))
        self.assertFalse(claude_service._is_prompt_line("$  hello"))

    def test_screen_reader_startup_banner_is_detected(self):
        self.assertTrue(claude_service._SCREEN_READER_START_RE.search("78Claude Code v2.1.240"))
        self.assertTrue(claude_service._SCREEN_READER_READY_RE.search("$ctrl+g to edit in Vim"))

    def test_screen_reader_echo_is_detected_with_or_without_prompt_prefix(self):
        message = "we're most interested in the state of our reference/ knowledge topologies. can you summarize?"
        self.assertTrue(claude_service._looks_like_echo(f"$  {message}", message))
        self.assertTrue(claude_service._looks_like_echo(message, message))
        self.assertTrue(claude_service._looks_like_echo(f"you: {message}", message))
        self.assertFalse(claude_service._looks_like_echo("Here is a summary.", message))

    def test_tool_prefix_variants_are_activity(self):
        self.assertEqual(claude_service._classify_line("⎿ Read foo.md"), [("activity", "Read foo.md")])
        self.assertEqual(claude_service._classify_line("⯎ Read foo.md"), [("activity", "Read foo.md")])

    def test_claude_prefix_lines_can_be_activity_or_answer(self):
        self.assertEqual(
            claude_service._extract_claude_text("$claude: Let me scan the reference directory structure."),
            "Let me scan the reference directory structure.",
        )
        self.assertEqual(
            claude_service._clean_answer_line("claude: Here's where the docs stand:"),
            "Here's where the docs stand:",
        )

    def test_answer_separator_and_screen_reader_prefix_cleanup(self):
        self.assertTrue(claude_service._is_answer_separator("$---"))
        self.assertTrue(claude_service._is_answer_separator("---"))
        self.assertEqual(
            claude_service._clean_answer_line("$ System Topology (system-topology.md) — Canon, v2.0."),
            "System Topology (system-topology.md) — Canon, v2.0.",
        )
        self.assertEqual(claude_service._clean_answer_line("$.0. The master document."), ".0. The master document.")

    def test_repaint_duplicate_detection(self):
        emitted = [
            "System Topology (system-topology.md) — Canon, v2.0. The master document.",
        ]
        self.assertTrue(
            claude_service._is_repaint_duplicate(
                "System Topology (system-topology.md) — Canon, v2.0. The master document.",
                emitted,
            )
        )
        self.assertTrue(
            claude_service._is_repaint_duplicate(
                "System Topology (system-topology.md) — Canon, v2.0.",
                emitted,
            )
        )
        self.assertFalse(claude_service._is_repaint_duplicate("Knowledge-Basing Topology — Pre-canon.", emitted))


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
