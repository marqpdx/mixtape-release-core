# atrium/ai/codebase_tools.py
#
# Read-only read_file/grep tools for the Atrium read-only bridge (Stage 1b).
# Scoped strictly to settings.ATRIUM_CODEBASE_ROOTS. No write_file, no
# run_command — by design, per decisions/atrium-adr/atrium-readonly-bridge-addendum.md.

from __future__ import annotations

import json
import re
from pathlib import Path

from django.conf import settings

MAX_FILE_BYTES = 200_000
MAX_GREP_MATCHES = 100
MAX_GREP_FILES = 200

_IGNORED_DIR_NAMES = {".git", "node_modules", "__pycache__", ".next", "dist", "build", ".turbo", "venv", "env"}


def _roots() -> dict[str, Path]:
    roots = getattr(settings, "ATRIUM_CODEBASE_ROOTS", {})
    return {name: Path(p) for name, p in roots.items()}


def _resolve(path: str) -> Path:
    if not path or "/" not in path:
        roots = sorted(_roots())
        raise ValueError(f"Path must start with one of: {roots}")

    prefix, _, rest = path.partition("/")
    roots = _roots()
    root = roots.get(prefix)
    if root is None:
        raise ValueError(f"Unknown root '{prefix}'. Allowed: {sorted(roots)}")

    root_resolved = root.resolve()
    resolved = (root_resolved / rest).resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ValueError("Path escapes the allowed checkout root.")
    return resolved


def _is_ignored(p: Path) -> bool:
    return any(part in _IGNORED_DIR_NAMES for part in p.parts)


def read_file(path: str) -> str:
    try:
        target = _resolve(path)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    if not target.is_file():
        return json.dumps({"error": f"Not a file: {path}"})
    if target.stat().st_size > MAX_FILE_BYTES:
        return json.dumps({"error": f"File too large (> {MAX_FILE_BYTES} bytes): {path}"})

    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return json.dumps({"error": f"File is not valid UTF-8 text: {path}"})

    return json.dumps({"path": path, "text": text})


def grep(pattern: str, path: str) -> str:
    try:
        target = _resolve(path)
        regex = re.compile(pattern)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    except re.error as exc:
        return json.dumps({"error": f"Invalid regex: {exc}"})

    if not target.exists():
        return json.dumps({"error": f"Path does not exist: {path}"})

    if target.is_dir():
        base_display = path.rstrip("/")
        candidates = [p for p in target.rglob("*") if p.is_file() and not _is_ignored(p)]
    else:
        base_display = None
        candidates = [target]

    matches: list[dict] = []
    files_scanned = 0
    for f in candidates:
        if files_scanned >= MAX_GREP_FILES or len(matches) >= MAX_GREP_MATCHES:
            break
        files_scanned += 1
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        display_path = f"{base_display}/{f.relative_to(target)}" if base_display else path
        for lineno, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                matches.append({"path": display_path, "line": lineno, "text": line.strip()[:300]})
                if len(matches) >= MAX_GREP_MATCHES:
                    break

    return json.dumps({
        "matches": matches,
        "files_scanned": files_scanned,
        "truncated": len(matches) >= MAX_GREP_MATCHES,
    })
