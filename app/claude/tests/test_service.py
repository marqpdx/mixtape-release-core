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


class TestLockdown(unittest.TestCase):
    """ST-2: no tools unless named, empty scratch cwd, no MCP/hooks/saved session."""

    def setUp(self):
        claude_service._cli_supports.cache_clear()

    def _ok(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "ok"
        mock_result.stderr = ""
        return mock_result

    def test_default_run_has_no_tools_and_no_mcp_or_hooks(self):
        with patch("claude.service._cli_supports", return_value=False), \
             patch("claude.service.subprocess.run", return_value=self._ok()) as mock_run:
            claude_service.run_blocking("say ok")
        cmd = mock_run.call_args.args[0]
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")
        self.assertIn("--disable-slash-commands", cmd)
        self.assertIn("--strict-mcp-config", cmd)
        self.assertIn('{"mcpServers":{}}', cmd)
        self.assertIn('{"disableAllHooks":true}', cmd)
        self.assertNotIn("--no-session-persistence", cmd)

    def test_named_tools_are_passed_through(self):
        with patch("claude.service._cli_supports", return_value=False), \
             patch("claude.service.subprocess.run", return_value=self._ok()) as mock_run:
            claude_service.run_blocking("read it", tools=claude_service.READ_ONLY_TOOLS)
        cmd = mock_run.call_args.args[0]
        self.assertEqual(cmd[cmd.index("--tools") + 1], "Read,Grep,Glob")

    def test_session_persistence_off_when_cli_supports_it(self):
        with patch("claude.service._cli_supports", return_value=True), \
             patch("claude.service.subprocess.run", return_value=self._ok()) as mock_run:
            claude_service.run_blocking("say ok")
        self.assertIn("--no-session-persistence", mock_run.call_args.args[0])

    def test_default_cwd_is_an_empty_scratch_dir_removed_afterwards(self):
        seen = {}

        def fake_run(cmd, **kwargs):
            seen["cwd"] = kwargs["cwd"]
            seen["empty"] = os.listdir(kwargs["cwd"]) == []
            return self._ok()

        with patch("claude.service._cli_supports", return_value=False), \
             patch("claude.service.subprocess.run", side_effect=fake_run):
            claude_service.run_blocking("say ok")
        self.assertTrue(os.path.basename(seen["cwd"]).startswith("claude-run-"))
        self.assertTrue(seen["empty"])
        self.assertFalse(os.path.exists(seen["cwd"]))

    def test_scratch_dir_removed_on_timeout(self):
        seen = {}

        def fake_run(cmd, **kwargs):
            seen["cwd"] = kwargs["cwd"]
            raise subprocess.TimeoutExpired("claude", 1)

        with patch("claude.service._cli_supports", return_value=False), \
             patch("claude.service.subprocess.run", side_effect=fake_run):
            result = claude_service.run_blocking("say ok")
        self.assertEqual(result.failure, "timeout")
        self.assertFalse(os.path.exists(seen["cwd"]))

    def test_session_gets_scratch_dir_removed_on_terminate(self):
        proc = MagicMock()
        proc.poll.return_value = None
        with patch("claude.service._cli_supports", return_value=False), \
             patch("claude.service.subprocess.Popen", return_value=proc) as mock_popen:
            claude_service.get_or_spawn("lockdown-session")
            kwargs = mock_popen.call_args.kwargs
            cmd = mock_popen.call_args.args[0]
            scratch = kwargs["cwd"]
            self.assertTrue(os.path.isdir(scratch))
            self.assertEqual(cmd[cmd.index("--tools") + 1], "")
            self.assertIn("--disable-slash-commands", cmd)
            claude_service.terminate_session("lockdown-session")
        self.assertFalse(os.path.exists(scratch))
        self.assertNotIn("lockdown-session", claude_service._session_registry)

    def test_atrium_style_session_keeps_slash_commands(self):
        proc = MagicMock()
        proc.poll.return_value = None
        with patch("claude.service._cli_supports", return_value=False), \
             patch("claude.service.subprocess.Popen", return_value=proc) as mock_popen:
            claude_service.get_or_spawn(
                "atrium-session", "/tmp",
                tools=claude_service.READ_ONLY_TOOLS, allow_slash_commands=True,
            )
            claude_service.terminate_session("atrium-session")
        cmd = mock_popen.call_args.args[0]
        self.assertEqual(mock_popen.call_args.kwargs["cwd"], "/tmp")
        self.assertNotIn("--disable-slash-commands", cmd)
        self.assertTrue(os.path.isdir("/tmp"))  # a caller's cwd is never removed


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
