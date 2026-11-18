"""Tests for tools/check_secret_literals.py.

Every fake value is assembled at run time, so this file never holds a literal the
checker would refuse and needs no allowance of its own. None is a real secret.

Run from the repository root:
    python3 -m unittest discover -s tools/tests -p "test_check_secret_literals.py"
"""

from __future__ import annotations

import contextlib
import io
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_secret_literals as csl  # noqa: E402

SETTINGS = "app/mixtape/settings/fake.py"
COMMAND = "app/accounts/management/commands/fake_cmd.py"
OTHER = "app/accounts/views.py"


def fake(n: int = 24) -> str:
    """A random-looking mixed-case alphanumeric fake, built at run time."""
    alphabet = "aB3dE5fG7hJ9" + "kL2mN4pQ6rS8" + "tU1vW0xYz"
    return "".join(alphabet[(i * 7 + 3) % len(alphabet)] for i in range(n))


def no_allow() -> csl.Allowlist:
    return csl.Allowlist(exclude=[], entries=[], placeholders=[])


def rules(findings: list[csl.Finding]) -> list[str]:
    return [f.rule for f in findings]


class PatternRules(unittest.TestCase):
    def check(self, text: str, rule: str) -> None:
        found = csl.scan_text("docs/notes.md", text, no_allow())
        self.assertIn(rule, rules(found), text)

    def test_private_key_block(self):
        self.check("-----BEGIN " + "RSA " + "PRIVATE KEY-----", "private-key-block")
        self.check("-----BEGIN " + "OPENSSH " + "PRIVATE KEY-----", "private-key-block")

    def test_aws_access_key(self):
        self.check("key = " + "AK" + "IA" + "X" * 16, "aws-access-key")

    def test_provider_keys(self):
        self.check("OPENAI=" + "sk" + "-" + fake(32), "provider-key")
        self.check("ANTHROPIC=" + "sk" + "-ant-" + fake(32), "provider-key")

    def test_github_and_slack_tokens(self):
        self.check("t=" + "gh" + "p_" + "A1" * 18, "github-token")
        self.check("t=" + "xo" + "xb-" + "1234-" + fake(12), "slack-token")

    def test_session_handle(self):
        uuid = "-".join(["1a2b3c4d", "5e6f", "7a8b", "9c0d", "1e2f3a4b5c6d"])
        self.check("codex " + "resume " + uuid, "session-handle")
        self.check("claude " + "--resume " + uuid, "session-handle")

    def test_high_entropy_string(self):
        self.check('x = "' + fake(40) + '"', "high-entropy-string")

    def test_high_entropy_skips_hex_identifiers_and_paths(self):
        for value in ["0123456789abcdef" * 3, "help-fidelity-01/run/blocks/argus/api",
                      "offline_diagnostic_lower_threshold_version_2", "abcdefghijklmnopqrstuvwxyz012345"]:
            found = csl.scan_text("docs/notes.md", f'x = "{value}"', no_allow())
            self.assertNotIn("high-entropy-string", rules(found), value)


class SecretAssignment(unittest.TestCase):
    def found(self, path: str, src: str, allow: csl.Allowlist | None = None) -> list[csl.Finding]:
        return [f for f in csl.scan_text(path, src, allow or no_allow()) if f.rule == "secret-assignment"]

    def test_assignment_in_settings(self):
        f = self.found(SETTINGS, f'DB_PASSWORD = "{fake(12)}"\n')
        self.assertEqual([(x.line, x.name) for x in f], [(1, "DB_PASSWORD")])

    def test_bootstrap_shape_in_management_command(self):
        src = f'def handle(self):\n    User.objects.create_superuser("root", password="{fake(12)}")\n'
        self.assertEqual([x.line for x in self.found(COMMAND, src)], [2])

    def test_getenv_default(self):
        src = f'import os\nSECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "{fake(16)}")\n'
        self.assertEqual([x.name for x in self.found(SETTINGS, src)], ["DJANGO_SECRET_KEY"])
        src = f'import os\nX = os.environ.get("API_TOKEN", "{fake(16)}")\n'
        self.assertEqual([x.name for x in self.found(SETTINGS, src)], ["API_TOKEN"])

    def test_dict_key_annassign_and_default_argument(self):
        src = (f'CONF = {{"client_secret": "{fake(12)}"}}\n'
               f'TOKEN: str = "{fake(12)}"\n'
               f'def f(api_key="{fake(12)}"):\n    pass\n')
        self.assertEqual([x.line for x in self.found(SETTINGS, src)], [1, 2, 3])

    def test_not_outside_settings_and_commands(self):
        self.assertEqual(self.found(OTHER, f'password = "{fake(12)}"\n'), [])

    def test_short_values_env_reads_and_non_secret_names_pass(self):
        src = ('import os\nPASSWORD_MIN = "abc"\n'
               'DB_PASSWORD = os.getenv("DB_PASSWORD")\n'
               f'USERNAME = "{fake(12)}"\n')
        self.assertEqual(self.found(SETTINGS, src), [])

    def test_placeholder_and_named_allowance(self):
        allow = csl.Allowlist(
            exclude=[],
            entries=[{"paths": [SETTINGS], "rules": ["secret-assignment"], "names": ["LIVEKIT_API_SECRET"],
                      "reason": "test"}],
            placeholders=[re.compile("dev-only", re.I)],
        )
        src = (f'import os\nA = os.getenv("LIVEKIT_API_SECRET", "{fake(10)}")\n'
               f'B = os.getenv("DJANGO_SECRET_KEY", "dev-only-{fake(6)}")\n'
               f'C = os.getenv("OTHER_SECRET", "{fake(10)}")\n')
        self.assertEqual([x.name for x in self.found(SETTINGS, src, allow)], ["OTHER_SECRET"])


class Allowlist(unittest.TestCase):
    def test_exclude_and_path_glob(self):
        allow = csl.Allowlist(
            exclude=["tools/eval/**/runs/"],
            entries=[{"paths": ["app/**/tests/*.py"], "rules": ["aws-access-key"], "reason": "test"}],
            placeholders=[],
        )
        line = "AK" + "IA" + "Q" * 16
        self.assertEqual(csl.scan_text("tools/eval/x/runs/a/b.json", line, allow), [])
        self.assertEqual(csl.scan_text("app/foo/tests/test_x.py", line, allow), [])
        self.assertEqual(rules(csl.scan_text("app/foo/views.py", line, allow)), ["aws-access-key"])

    def test_repo_allowlist_loads_and_every_entry_has_a_reason(self):
        allow = csl.load_allowlist()
        self.assertTrue(allow.excluded("tools/eval/folio-ner/runs/2026-11-06/out.json"))

    def test_entry_without_reason_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.toml"
            p.write_text('[[allow]]\npaths = ["x"]\nrules = ["provider-key"]\n')
            with self.assertRaises(SystemExit):
                csl.load_allowlist(p)


class Output(unittest.TestCase):
    def test_reports_file_line_rule_and_never_the_value(self):
        secret = fake(20)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "leak.txt"
            p.write_text("ok\nkey: " + "sk" + "-" + secret + "\n")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = csl.main([str(p)])
        self.assertEqual(code, 1)
        self.assertIn(":2 provider-key", out.getvalue())
        self.assertNotIn(secret, out.getvalue())
        self.assertNotIn(secret[:8], out.getvalue())


if __name__ == "__main__":
    unittest.main()
