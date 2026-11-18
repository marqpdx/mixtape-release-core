#!/usr/bin/env python3
"""
check_secret_literals.py — keep secret values out of this public repository.

A bootstrap password literal sat in a management command, and in history, until
the 2026-11-17 scrub, and nothing stopped it being committed. This check is the
gate in front of the Argus audit block public-release-readiness-01, which still
owns history and the shapes a gate can't see.

It fails on any of these, outside the allowances in tools/secret-literals.toml:

  secret-assignment     in app/**/settings/*.py and app/**/management/commands/*.py:
                        a secret-named name (password, secret, token, api_key,
                        private_key, credential, ...) given a string literal: an
                        assignment, a keyword argument, a dict key, or the default
                        of os.getenv / os.environ.get for a secret-named variable
  private-key-block     a PEM private-key header, in any tracked text file
  aws-access-key        an AWS access-key id (AKIA/ASIA + 16)
  provider-key          an sk- / sk-ant- style API key
  github-token          a GitHub token (gh?_..., github_pat_...)
  slack-token           a Slack token (xox?-...)
  high-entropy-string   a quoted string of 32+ key-like characters, mixed letters
                        and digits, high Shannon entropy, not plain hex
  session-handle        an AI-CLI session handle: `codex resume <uuid>`,
                        `claude --resume <uuid>` (or `-r`)

Output is `file:line rule-name` only. The matched text is never printed.

Adding an allowance is a decision: give its reason in the TOML entry.

Standard library only. Run from the repository root:
    python3 tools/check_secret_literals.py            # every tracked file (CI)
    python3 tools/check_secret_literals.py --staged   # what this commit adds (hook)
    python3 tools/check_secret_literals.py PATH ...   # these files
"""

from __future__ import annotations

import argparse
import ast
import math
import re
import subprocess
import sys
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = ROOT / "tools" / "secret-literals.toml"

MAX_BYTES = 2_000_000  # larger files are generated bundles or data; skip them

SECRET_NAME_RE = re.compile(
    r"(pass(word|wd|phrase)?|secret|token|api_?key|private_?key|credential|signing_?key|auth_?key|access_?key)",
    re.IGNORECASE,
)
MIN_SECRET_LITERAL = 6

ASSIGNMENT_SCOPES = ("app/**/settings/*.py", "app/**/management/commands/*.py")

PATTERN_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("private-key-block", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----")),
    ("aws-access-key", re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Z0-9])")),
    ("provider-key", re.compile(r"(?<![A-Za-z0-9])sk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}")),
    ("github-token", re.compile(r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("slack-token", re.compile(r"(?<![A-Za-z0-9])xox[abposr]-[A-Za-z0-9-]{10,}")),
    ("session-handle", re.compile(
        r"\b(?:codex\s+resume|claude\s+(?:--resume|-r))\s+[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
    )),
]

QUOTED_RE = re.compile(r"""(["'`])([A-Za-z0-9+/=_\-]{32,})\1""")
HEX_RE = re.compile(r"[0-9a-fA-F]+")
MIN_ENTROPY = 4.0


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    name: str = ""  # the secret-named name, for secret-assignment (a name, never a value)

    def __str__(self) -> str:
        return f"{self.path}:{self.line} {self.rule}"


# --- globs and the allowlist ------------------------------------------------

def glob_to_re(pattern: str) -> re.Pattern[str]:
    """`**` crosses directories, `*` and `?` stay within one; a trailing `/` means everything under it."""
    if pattern.endswith("/"):
        pattern += "**"
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(glob_to_re(p).match(path) for p in patterns)


@dataclass
class Allowlist:
    exclude: list[str]
    entries: list[dict]
    placeholders: list[re.Pattern[str]]

    def excluded(self, path: str) -> bool:
        return matches_any(path, self.exclude)

    def allows(self, f: Finding) -> bool:
        for entry in self.entries:
            if not matches_any(f.path, entry["paths"]):
                continue
            if f.rule not in entry["rules"]:
                continue
            names = entry.get("names")
            if names is not None and f.name not in names:
                continue
            return True
        return False

    def is_placeholder(self, value: str) -> bool:
        return any(p.search(value) for p in self.placeholders)


def load_allowlist(path: Path = ALLOWLIST) -> Allowlist:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    exclude: list[str] = []
    for entry in data.get("exclude", []):
        _require_reason(entry, "exclude")
        exclude.extend(entry["paths"])
    entries = []
    for entry in data.get("allow", []):
        _require_reason(entry, "allow")
        unknown = set(entry["rules"]) - RULE_NAMES
        if unknown:
            raise SystemExit(f"tools/secret-literals.toml: unknown rule(s) {sorted(unknown)}")
        entries.append(entry)
    placeholders = []
    for entry in data.get("placeholder", []):
        _require_reason(entry, "placeholder")
        placeholders.extend(re.compile(p, re.IGNORECASE) for p in entry["patterns"])
    return Allowlist(exclude=exclude, entries=entries, placeholders=placeholders)


def _require_reason(entry: dict, kind: str) -> None:
    if not str(entry.get("reason", "")).strip():
        raise SystemExit(f"tools/secret-literals.toml: every [[{kind}]] entry needs a reason")


# --- the rules ---------------------------------------------------------------

def shannon_entropy(s: str) -> float:
    counts = Counter(s)
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def looks_high_entropy(s: str) -> bool:
    if HEX_RE.fullmatch(s):
        return False  # hashes and commit ids
    if not (re.search(r"[a-z]", s) and re.search(r"[A-Z]", s) and re.search(r"[0-9]", s)):
        return False  # generated keys mix all three; identifiers, slugs and paths rarely do
    segments = [seg for seg in re.split(r"[/_\-.]", s) if seg]
    if len(segments) >= 3 and all(seg.isalpha() or seg.isdigit() for seg in segments):
        return False  # snake_case, kebab-case, dotted or slashed words
    return shannon_entropy(s) >= MIN_ENTROPY


def scan_patterns(path: str, text: str) -> list[Finding]:
    found = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for rule, rx in PATTERN_RULES:
            if rx.search(line):
                found.append(Finding(path, lineno, rule))
        for m in QUOTED_RE.finditer(line):
            if looks_high_entropy(m.group(2)):
                found.append(Finding(path, lineno, "high-entropy-string"))
                break
    return found


def _secret_name(name: str | None) -> bool:
    return bool(name) and bool(SECRET_NAME_RE.search(name))


def _str_literal(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _target_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Attribute):
        return [target.attr]
    if isinstance(target, ast.Subscript):
        key = _str_literal(target.slice)
        return [key] if key else []
    if isinstance(target, (ast.Tuple, ast.List)):
        return [n for elt in target.elts for n in _target_names(elt)]
    return []


def _is_getenv(func: ast.AST) -> bool:
    # os.getenv(...), getenv(...), os.environ.get(...), environ.get(...)
    if isinstance(func, ast.Name):
        return func.id == "getenv"
    if isinstance(func, ast.Attribute):
        if func.attr == "getenv":
            return True
        if func.attr == "get":
            v = func.value
            return (isinstance(v, ast.Attribute) and v.attr == "environ") or (
                isinstance(v, ast.Name) and v.id == "environ"
            )
    return False


class AssignmentCheck(ast.NodeVisitor):
    def __init__(self, path: str, allow: Allowlist):
        self.path = path
        self.allow = allow
        self.found: list[Finding] = []

    def _consider(self, node: ast.AST, name: str | None, value: str | None) -> None:
        if not _secret_name(name) or value is None:
            return
        if len(value) < MIN_SECRET_LITERAL or self.allow.is_placeholder(value):
            return
        self.found.append(Finding(self.path, getattr(node, "lineno", 0), "secret-assignment", name or ""))

    def visit_Assign(self, node: ast.Assign) -> None:
        value = _str_literal(node.value)
        for target in node.targets:
            for name in _target_names(target):
                self._consider(node, name, value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        for name in _target_names(node.target):
            self._consider(node, name, _str_literal(node.value))
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        for key, value in zip(node.keys, node.values):
            self._consider(value, _str_literal(key), _str_literal(value))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        args = node.args
        positional = args.posonlyargs + args.args
        for arg, default in zip(positional[len(positional) - len(args.defaults):], args.defaults):
            self._consider(default, arg.arg, _str_literal(default))
        for arg, default in zip(args.kwonlyargs, args.kw_defaults):
            self._consider(default or arg, arg.arg, _str_literal(default))
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        for kw in node.keywords:
            self._consider(kw.value, kw.arg, _str_literal(kw.value))
        if _is_getenv(node.func) and len(node.args) >= 2:
            self._consider(node, _str_literal(node.args[0]), _str_literal(node.args[1]))
        self.generic_visit(node)


def scan_assignments(path: str, text: str, allow: Allowlist) -> list[Finding]:
    if not path.endswith(".py") or not matches_any(path, list(ASSIGNMENT_SCOPES)):
        return []
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError:
        return [Finding(path, 0, "unparseable")]
    check = AssignmentCheck(path, allow)
    check.visit(tree)
    return check.found


RULE_NAMES = {r for r, _ in PATTERN_RULES} | {"high-entropy-string", "secret-assignment"}


def scan_text(path: str, text: str, allow: Allowlist) -> list[Finding]:
    """Every finding in one file's text that the allowlist doesn't cover."""
    if allow.excluded(path):
        return []
    found = scan_patterns(path, text) + scan_assignments(path, text, allow)
    return sorted({f for f in found if not allow.allows(f)}, key=lambda f: (f.line, f.rule))


# --- which files -------------------------------------------------------------

def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True).stdout


def _decode(data: bytes) -> str | None:
    if len(data) > MAX_BYTES or b"\0" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def tracked_files() -> list[tuple[str, str]]:
    out = []
    for rel in _git("ls-files", "-z").decode().split("\0"):
        if not rel:
            continue
        p = ROOT / rel
        if not p.is_file() or p.is_symlink():
            continue
        text = _decode(p.read_bytes())
        if text is not None:
            out.append((rel, text))
    return out


def staged_files() -> list[tuple[str, str]]:
    """The staged (index) content of each added, copied, modified or renamed file."""
    names = _git("diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR").decode().split("\0")
    out = []
    for rel in names:
        if not rel:
            continue
        text = _decode(_git("show", f":{rel}"))
        if text is not None:
            out.append((rel, text))
    return out


def given_files(paths: list[str]) -> list[tuple[str, str]]:
    out = []
    for raw in paths:
        p = Path(raw).resolve()
        try:
            rel = p.relative_to(ROOT).as_posix()
        except ValueError:
            rel = Path(raw).as_posix()
        text = _decode(p.read_bytes())
        if text is not None:
            out.append((rel, text))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refuse secret literals (prints file:line rule only).")
    parser.add_argument("--staged", action="store_true", help="check the staged content of this commit")
    parser.add_argument("paths", nargs="*", help="check these files instead of every tracked file")
    args = parser.parse_args(argv)

    allow = load_allowlist()
    if args.staged:
        files = staged_files()
    elif args.paths:
        files = given_files(args.paths)
    else:
        files = tracked_files()

    findings = [f for rel, text in files for f in scan_text(rel, text, allow)]
    if findings:
        print("Secret-literal check failed. Each line is a file, a line and the rule it broke:\n")
        for f in findings:
            print(f"  {f}")
        print(
            "\nMove the value to the environment. If it is a test"
            " fixture or a documented placeholder, add an allowance with its reason to"
            " tools/secret-literals.toml."
        )
        return 1
    print(f"Secret-literal check passed ({len(files)} files).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
