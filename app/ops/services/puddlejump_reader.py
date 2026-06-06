from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from django.conf import settings
from django.utils import timezone


CHECKPOINT_DONE = "✅"
CHECKPOINT_IN_PROGRESS = "🔶"
CHECKPOINT_PENDING = "🔲"
COMMIT_SEPARATOR = " — "
FRONTMATTER_DELIMITER = "---"
BUILD_LOG_SOURCE = "build_log"
INBOX_SOURCE = "inbox"
CANONICAL_BUILD_LOG_FILENAME = "build-log.md"
BUILD_LOG_HEADING_PATTERN = re.compile(r"^###\s+(\d{4}-\d{2}-\d{2})\s+—\s+(.+)$")
BUILD_LOG_COMMIT_PATTERN = re.compile(r"^(?:(?P<repo>[A-Za-z0-9_.-]+)\s+)?`(?P<commit>[^`]+)`$")
BUILD_LOG_WORK_EFFORT_PATTERN = re.compile(r"^_Work effort:\s*(.+)_$")


@dataclass(frozen=True)
class PuddlejumpPathState:
    available: bool
    root: Path | None = None
    reason: str = ""


def build_project_status() -> dict[str, Any]:
    path_state = _resolve_puddlejump_path()
    generated_at = timezone.now().isoformat()

    if not path_state.available or path_state.root is None:
        return {
            "available": False,
            "generated_at": generated_at,
            "reason": path_state.reason,
            "decisions": [],
            "timeline": [],
            "unprocessed_inbox_count": 0,
        }

    inbox_entries = read_build_log_inbox(path_state.root)

    return {
        "available": True,
        "generated_at": generated_at,
        "root": str(path_state.root),
        "decisions": read_decision_documents(path_state.root),
        "timeline": read_build_log_timeline(path_state.root, inbox_entries=inbox_entries),
        "unprocessed_inbox_count": len(inbox_entries),
    }


def _resolve_puddlejump_path() -> PuddlejumpPathState:
    configured = getattr(settings, "PUDDLEJUMP_PATH", None)
    if not configured:
        return PuddlejumpPathState(False, reason="PUDDLEJUMP_PATH is not configured.")

    root = Path(str(configured)).expanduser()
    if not root.exists():
        return PuddlejumpPathState(False, reason=f"PUDDLEJUMP_PATH does not exist: {root}")
    if not root.is_dir():
        return PuddlejumpPathState(False, reason=f"PUDDLEJUMP_PATH is not a directory: {root}")

    return PuddlejumpPathState(True, root=root)


def read_decision_documents(puddlejump_root: Path) -> list[dict[str, Any]]:
    decisions_root = puddlejump_root / "decisions"
    if not decisions_root.is_dir():
        return []

    rows = []
    for file_path in sorted(decisions_root.rglob("*.md")):
        if _should_skip_path(file_path):
            continue
        relative_path = file_path.relative_to(puddlejump_root).as_posix()
        text = _read_text(file_path)
        header = _parse_blockquote_header(text)
        checkpoints = read_checkpoint_counts(text)
        status = header.get("status", "")
        queue_state = _derive_queue_state(status, checkpoints)
        rows.append(
            {
                "path": relative_path,
                "name": _extract_title(text, file_path.stem),
                "class": header.get("class", ""),
                "status": status,
                "library": header.get("library", ""),
                "last_updated": header.get("last updated") or header.get("last-updated") or "",
                "checkpoint_counts": checkpoints,
                "queue_state": queue_state,
            }
        )
    return rows


def read_checkpoint_counts(text: str) -> dict[str, int]:
    done = text.count(CHECKPOINT_DONE)
    in_progress = text.count(CHECKPOINT_IN_PROGRESS)
    pending = text.count(CHECKPOINT_PENDING)
    total = done + in_progress + pending
    return {
        "total": total,
        "done": done,
        "in_progress": in_progress,
        "pending": pending,
    }


def read_build_log_timeline(
    puddlejump_root: Path,
    inbox_entries: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    canonical_entries = read_canonical_build_log(puddlejump_root)
    combined_entries = list(canonical_entries)
    seen_keys = {_timeline_entry_key(entry) for entry in canonical_entries}

    for entry in inbox_entries if inbox_entries is not None else read_build_log_inbox(puddlejump_root):
        key = _timeline_entry_key(entry)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        combined_entries.append(entry)

    combined_entries.sort(
        key=lambda item: (
            item["date"],
            1 if item.get("source") == INBOX_SOURCE else 0,
            item["repo"],
            item["commit_hash"],
        ),
        reverse=True,
    )
    return combined_entries


def read_canonical_build_log(puddlejump_root: Path) -> list[dict[str, Any]]:
    build_log_path = puddlejump_root / CANONICAL_BUILD_LOG_FILENAME
    if not build_log_path.is_file():
        return []

    text = _read_text(build_log_path)
    entries = []
    current_heading: re.Match[str] | None = None
    current_lines: list[str] = []

    for line in text.splitlines():
        heading = BUILD_LOG_HEADING_PATTERN.match(line.strip())
        if heading:
            entries.extend(_parse_canonical_build_log_section(current_heading, current_lines))
            current_heading = heading
            current_lines = []
            continue
        if current_heading:
            current_lines.append(line)

    entries.extend(_parse_canonical_build_log_section(current_heading, current_lines))
    return entries


def read_build_log_inbox(puddlejump_root: Path) -> list[dict[str, Any]]:
    inbox_root = puddlejump_root / "build-log-inbox"
    if not inbox_root.is_dir():
        return []

    entries = []
    for file_path in sorted(inbox_root.glob("*.md")):
        parsed = _parse_build_log_file(file_path)
        if parsed:
            entries.append(parsed)

    entries.sort(key=lambda item: (item["date"], item["source_filename"]), reverse=True)
    return entries


def _parse_canonical_build_log_section(
    heading: re.Match[str] | None,
    lines: list[str],
) -> list[dict[str, Any]]:
    if heading is None:
        return []

    try:
        entry_date = date.fromisoformat(heading.group(1))
    except ValueError:
        return []

    commits = _parse_canonical_commit_specs(heading.group(2))
    if not commits:
        return []

    work_effort = ""
    body_lines = []
    for line in lines:
        stripped = line.strip()
        work_effort_match = BUILD_LOG_WORK_EFFORT_PATTERN.match(stripped)
        if work_effort_match:
            work_effort = work_effort_match.group(1).strip()
            continue
        if stripped == FRONTMATTER_DELIMITER:
            continue
        body_lines.append(line)

    body = "\n".join(body_lines).strip()
    return [
        {
            "date": entry_date.isoformat(),
            "repo": repo,
            "commit_hash": commit_hash,
            "commit_message": "",
            "work_effort": work_effort,
            "body": body,
            "source": BUILD_LOG_SOURCE,
            "source_filename": CANONICAL_BUILD_LOG_FILENAME,
        }
        for repo, commit_hash in commits
    ]


def _parse_canonical_commit_specs(raw_specs: str) -> list[tuple[str, str]]:
    commits = []
    current_repo = ""
    for raw_part in raw_specs.split(" + "):
        part = raw_part.strip()
        match = BUILD_LOG_COMMIT_PATTERN.match(part)
        if not match:
            return []

        repo = (match.group("repo") or current_repo).strip()
        commit_hash = match.group("commit").strip()
        if not repo or not commit_hash:
            return []

        current_repo = repo
        commits.append((repo, commit_hash))

    return commits


def _parse_build_log_file(file_path: Path) -> dict[str, Any] | None:
    text = _read_text(file_path)
    try:
        metadata, body = _split_frontmatter(text)
        commit_hash, commit_message = _parse_commit(metadata.get("commit", ""))
        entry_date = date.fromisoformat(metadata.get("date", "").strip())
        repo = metadata.get("repo", "").strip()
        if not repo:
            return None
    except (ValueError, TypeError):
        return None

    return {
        "date": entry_date.isoformat(),
        "repo": repo,
        "commit_hash": commit_hash,
        "commit_message": commit_message,
        "work_effort": metadata.get("work_effort", "").strip(),
        "body": body.strip(),
        "source": INBOX_SOURCE,
        "source_filename": file_path.name,
    }


def _timeline_entry_key(entry: dict[str, Any]) -> tuple[str, str]:
    return (entry.get("repo", ""), entry.get("commit_hash", ""))


def _parse_blockquote_header(text: str) -> dict[str, str]:
    header: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith(">"):
            break

        content = stripped.lstrip(">").strip()
        match = re.match(r"\*\*(.+?)\:\*\*\s*(.+)", content)
        if match:
            key = match.group(1).strip().lower()
            header[key] = match.group(2).strip()
    return header


def _extract_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback.replace("-", " ").replace("_", " ").title()


def _derive_queue_state(status: str, checkpoints: dict[str, int]) -> str:
    normalized_status = status.lower()
    if "blocked" in normalized_status or "pending cto sign-off" in normalized_status:
        return "blocked"

    total = checkpoints["total"]
    done = checkpoints["done"]
    in_progress = checkpoints["in_progress"]
    pending = checkpoints["pending"]

    if total == 0:
        if "complete" in normalized_status or "closed" in normalized_status:
            return "complete"
        return "pending"
    if done == total:
        return "complete"
    if done > 0 or in_progress > 0:
        return "in_progress"
    if pending == total:
        return "pending"
    return "pending"


def _split_frontmatter(raw_text: str) -> tuple[dict[str, str], str]:
    lines = raw_text.splitlines()
    if len(lines) < 3 or lines[0].strip() != FRONTMATTER_DELIMITER:
        raise ValueError("Missing opening frontmatter delimiter.")

    closing_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == FRONTMATTER_DELIMITER:
            closing_index = index
            break

    if closing_index is None:
        raise ValueError("Missing closing frontmatter delimiter.")

    metadata: dict[str, str] = {}
    for line in lines[1:closing_index]:
        stripped_line = line.strip()
        if not stripped_line:
            continue
        if ":" not in stripped_line:
            raise ValueError(f"Malformed frontmatter line: {line}")
        key, value = stripped_line.split(":", 1)
        metadata[key.strip()] = value.strip()

    return metadata, "\n".join(lines[closing_index + 1 :]).strip()


def _parse_commit(commit_value: str) -> tuple[str, str]:
    commit_value = commit_value.strip()
    if not commit_value or COMMIT_SEPARATOR not in commit_value:
        raise ValueError("Commit field must contain an em dash separator.")

    commit_hash, commit_message = commit_value.split(COMMIT_SEPARATOR, 1)
    commit_hash = commit_hash.strip()
    if not commit_hash:
        raise ValueError("Commit hash is empty.")

    return commit_hash, commit_message.strip()


def _read_text(file_path: Path) -> str:
    return file_path.read_text(encoding="utf-8", errors="replace")


def _should_skip_path(file_path: Path) -> bool:
    return any(part.startswith(".") for part in file_path.parts)
