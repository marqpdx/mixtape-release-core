#!/usr/bin/env python3
"""
check_data_routes.py — keep core's AI and outside calls where the charter says they are.

Service Trust ST-12 (CTO, 2026-10-27). The charter "Where your data goes"
(puddlejump/decisions/positions/charter-where-your-data-goes.md) is the promise;
the Service Map (puddlejump/reference/knowledge-architecture/service-map.md) is
the evidence; this check stops the code drifting from both without anyone noticing.

It fails when, outside the approved places listed in tools/data-routes.toml:

  1. a module imports a cloud model SDK (anthropic, openai);
  2. code launches the claude or codex CLI itself instead of through the shared
     runners (claude/service.py, codex/service.py);
  3. a call to the shared Claude runner does not name its tools (`tools=`);
  4. an http(s) host appears in code that is not on the allowlist.

Limits: hosts built from settings or the environment (Inkwell, Stackroom, Switchboard)
are not seen here; the Argus block data-routes-01 checks the deployed settings.

Adding an entry to the allowlist is a decision: say which Service Map route it
travels and why, and update the Service Map in the same change.

Standard library only. Run from the repository root:
    python3 tools/check_data_routes.py
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
ALLOWLIST = ROOT / "tools" / "data-routes.toml"

CLOUD_SDKS = {"anthropic", "openai"}
CLAUDE_RUNNER_FUNCS = {
    "run_blocking", "run_session_blocking", "get_or_spawn", "send_to_session", "stream", "compact_pty",
}
CLI_NAMES = {"claude", "codex"}
CLI_BIN_HELPERS = {"_claude_bin", "_codex_bin"}
HOST_RE = re.compile(r"https?://([A-Za-z0-9.-]+)")
SKIP_PARTS = {"tests", "test", "migrations", "__pycache__", "node_modules"}


def _skip(path: Path) -> bool:
    rel = path.relative_to(APP)
    return any(part in SKIP_PARTS for part in rel.parts) or rel.name.startswith(("test_", "tests_"))


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _matches(rel: str, patterns: list[str]) -> bool:
    return any(rel == p or (p.endswith("/") and rel.startswith(p)) for p in patterns)


class FileCheck(ast.NodeVisitor):
    def __init__(self, rel: str, allow: dict):
        self.rel = rel
        self.allow = allow
        self.problems: list[str] = []
        self.runner_aliases: set[str] = set()   # `from claude import service as X`
        self.runner_names: set[str] = set()     # `from claude.service import run_blocking`

    def _flag(self, node: ast.AST, message: str) -> None:
        self.problems.append(f"{self.rel}:{getattr(node, 'lineno', 0)}: {message}")

    # 1. cloud SDK imports, and tracking the Claude runner's names
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top in CLOUD_SDKS and not _matches(self.rel, self.allow["sdk_imports"].get(top, [])):
                self._flag(node, f"imports cloud SDK '{top}' outside the approved places")
            if alias.name == "claude.service":
                self.runner_aliases.add(alias.asname or "claude")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        top = (node.module or "").split(".")[0]
        if top in CLOUD_SDKS and not _matches(self.rel, self.allow["sdk_imports"].get(top, [])):
            self._flag(node, f"imports cloud SDK '{top}' outside the approved places")
        if node.module == "claude":
            for alias in node.names:
                if alias.name == "service":
                    self.runner_aliases.add(alias.asname or "service")
        if node.module == "claude.service":
            for alias in node.names:
                if alias.name in CLAUDE_RUNNER_FUNCS:
                    self.runner_names.add(alias.asname or alias.name)
                if alias.name in CLI_BIN_HELPERS and not _matches(self.rel, self.allow["cli_launchers"]):
                    self._flag(node, f"uses {alias.name} to launch the CLI outside the shared runners")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in CLI_BIN_HELPERS and not _matches(self.rel, self.allow["cli_launchers"]):
            self._flag(node, f"uses {node.id} to launch the CLI outside the shared runners")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # 2. launching the claude/codex CLI directly
        if node.args and isinstance(node.args[0], (ast.List, ast.Tuple)) and node.args[0].elts:
            first = node.args[0].elts[0]
            if (isinstance(first, ast.Constant) and first.value in CLI_NAMES
                    and not _matches(self.rel, self.allow["cli_launchers"])):
                self._flag(node, f"launches the {first.value} CLI directly; use the shared runner")
        # 3. Claude runner calls must name their tools
        func = node.func
        is_runner_call = (
            (isinstance(func, ast.Attribute) and func.attr in CLAUDE_RUNNER_FUNCS
             and isinstance(func.value, ast.Name) and func.value.id in self.runner_aliases)
            or (isinstance(func, ast.Name) and func.id in self.runner_names)
        )
        if is_runner_call and not any(k.arg == "tools" for k in node.keywords):
            if not _matches(self.rel, self.allow["cli_launchers"]):
                self._flag(node, "calls the Claude runner without naming its tools (tools=...)")
        self.generic_visit(node)

    # 4. outbound hosts
    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            for host in HOST_RE.findall(node.value):
                host = host.lower().rstrip(".")
                if "." not in host:  # localhost, or a fragment of an f-string
                    continue
                if host not in self.allow["hosts"]:
                    self._flag(node, f"names host '{host}', which is not on the allowlist")
        self.generic_visit(node)


def load_allowlist() -> dict:
    data = tomllib.loads(ALLOWLIST.read_text())
    hosts = {}
    for entry in data.get("host", []):
        for host in entry["hosts"]:
            hosts[host.lower()] = entry
    return {
        "sdk_imports": {e["sdk"]: e["paths"] for e in data.get("sdk_import", [])},
        "cli_launchers": [p for e in data.get("cli_launcher", []) for p in e["paths"]],
        "hosts": hosts,
    }


def main() -> int:
    allow = load_allowlist()
    problems: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        if _skip(path):
            continue
        rel = _rel(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except SyntaxError as exc:
            problems.append(f"{rel}: could not parse ({exc})")
            continue
        check = FileCheck(rel, allow)
        check.visit(tree)
        problems.extend(check.problems)

    if problems:
        print("Data routes check failed. Each line is a call path the charter has not approved:\n")
        for line in problems:
            print(f"  {line}")
        print(
            "\nIf the route is intended, add it to tools/data-routes.toml with its Service Map route"
            " and reason, and update the Service Map in the same change."
        )
        return 1
    print("Data routes check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
