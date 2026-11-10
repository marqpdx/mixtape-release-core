# surfaces/services/argus_blocks.py
#
# Reads the Argus block registry from Puddlejump's filesystem -- the same
# PUDDLEJUMP_PATH mechanism the ops dashboard already uses
# (ops.services.puddlejump_reader), reused rather than duplicated. Not
# configured on Crossroads today (dev-only; see PUDDLEJUMP_PATH in
# mixtape.settings), so every function here degrades to "unavailable"
# instead of raising, matching the ops dashboard's own posture and the
# Argus API sketch's "not reachable" stance for anything Cass-dependent.
#
# This also closes the AC-4c gap noted in initiatives.services.findings:
# a block's declared finding_types live in this same frontmatter.

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ops.services.puddlejump_reader import resolve_puddlejump_path

RUN_FILENAME_RE = re.compile(r"^(?P<slug>[a-z][a-z0-9-]*)-(?P<date>\d{4}-\d{2}-\d{2})\.md$")


@dataclass(frozen=True)
class AuditBlock:
    slug: str
    domain: str
    block_state: str
    finding_types: list[str] = field(default_factory=list)
    last_run_at: str | None = None  # ISO date, from the latest audit-runs/*.md filename


def _parse_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    data = yaml.safe_load(parts[1]) or {}
    return data if isinstance(data, dict) else {}


def _latest_run_dates(puddlejump_root: Path) -> dict[str, str]:
    """block slug -> latest run date (YYYY-MM-DD), from audit-runs/*.md filenames."""
    runs_root = puddlejump_root / "decisions" / "argus" / "audit-runs"
    if not runs_root.is_dir():
        return {}
    latest: dict[str, str] = {}
    for file_path in runs_root.glob("*.md"):
        match = RUN_FILENAME_RE.match(file_path.name)
        if not match:
            continue
        slug, run_date = match["slug"], match["date"]
        if slug not in latest or run_date > latest[slug]:
            latest[slug] = run_date
    return latest


def read_audit_blocks() -> tuple[list[AuditBlock], str]:
    """
    Returns (blocks, unavailable_reason). blocks is [] and unavailable_reason
    is non-empty when PUDDLEJUMP_PATH isn't configured (today's reality on
    Crossroads) or the audit-blocks directory can't be read.
    """
    path_state = resolve_puddlejump_path()
    if not path_state.available or path_state.root is None:
        return [], path_state.reason

    blocks_root = path_state.root / "decisions" / "argus" / "audit-blocks"
    if not blocks_root.is_dir():
        return [], f"No audit-blocks directory at {blocks_root}"

    latest_runs = _latest_run_dates(path_state.root)
    blocks = []
    for file_path in sorted(blocks_root.glob("*.md")):
        header = _parse_frontmatter(file_path.read_text(encoding="utf-8"))
        slug = header.get("block")
        if not slug:
            continue
        blocks.append(
            AuditBlock(
                slug=slug,
                domain=header.get("domain", ""),
                block_state=header.get("block_state", ""),
                finding_types=list(header.get("finding_types") or []),
                last_run_at=latest_runs.get(slug),
            )
        )
    return blocks, ""


def read_audit_block(slug: str) -> tuple[AuditBlock | None, str]:
    blocks, reason = read_audit_blocks()
    if reason:
        return None, reason
    for block in blocks:
        if block.slug == slug:
            return block, ""
    return None, f"No audit block named '{slug}'"
