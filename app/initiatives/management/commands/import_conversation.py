# initiatives/management/commands/import_conversation.py
"""
Import an externally-exported conversation (Claude Web, ChatGPT) into an
ApertureLog-backed Initiative.

Usage:
    python manage.py import_conversation <path-to-export.md> \\
        --group <group-slug> \\
        [--platform claude|chatgpt] \\
        [--title "Override title"] \\
        [--author-name ml] \\
        [--output-dir ./extracted-docs]

The export format for --platform claude is the markdown export produced by
claude.ai: YAML frontmatter followed by alternating
    # Human — <timestamp>
    # Claude — <timestamp>
section headers.

Each turn becomes a prose ApertureLogEntry. Turns detected as standalone
documents (long structured Claude responses) are extracted to --output-dir
and replaced in the log with a stub + ledger_data reference. Two ledger
bookends (session_started / session_ended) bracket the stream.
"""

import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import yaml
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from groups.models import Group
from initiatives.models import (
    ApertureLog,
    ApertureLogEntry,
    ApertureLogEntryKind,
    Initiative,
    InitiativeStatus,
    LedgerEventType,
)

TURN_RE = re.compile(r"^# (Human|Claude) — (.+)$", re.MULTILINE)
SOURCE_URL_RE = re.compile(r"https://claude\.ai/chat/([a-f0-9-]{36})")
HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
H2_PLUS_RE = re.compile(r"^#{2,6}\s+", re.MULTILINE)
ATTACHMENT_HEADER_RE = re.compile(r"^\*\*Attachment:[^*]+\*\*\s*\n?")
YAML_TITLE_RE = re.compile(r"^title:\s*(.+)$", re.MULTILINE | re.IGNORECASE)

# e.g. "Aug 7, 2026, 11:53 AM"
_TS_FORMAT = "%b %d, %Y, %I:%M %p"

# Document detection thresholds
_DOC_CHAR_THRESHOLD = 6000      # always extract if body this long
_DOC_HEADING_COUNT = 3          # extract if >= this many ## headings
_DOC_H1_CHAR_THRESHOLD = 2000  # extract if has a # heading and body this long


def _parse_turn_timestamp(ts_str: str) -> datetime | None:
    try:
        naive = datetime.strptime(ts_str.strip(), _TS_FORMAT)
        return naive.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_claude_markdown(text: str) -> tuple[dict, list[dict]]:
    """
    Returns (frontmatter_dict, turns_list).
    Each turn: {role: 'Human'|'Claude', timestamp: str, body: str, index: int}
    """
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("No YAML frontmatter found. Expected --- delimiters.")

    frontmatter = yaml.safe_load(parts[1]) or {}
    body = parts[2]

    matches = list(TURN_RE.finditer(body))
    if not matches:
        raise ValueError("No turn headers found (expected '# Human —' or '# Claude —').")

    turns = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        ts_str = match.group(2).strip()
        turns.append(
            {
                "role": match.group(1),
                "timestamp": ts_str,
                "parsed_timestamp": _parse_turn_timestamp(ts_str),
                "body": body[start:end].strip(),
                "index": i,
            }
        )

    return frontmatter, turns


def _is_document(body: str, role: str) -> bool:
    """Heuristic: is this turn a standalone document rather than a conversational reply?"""
    if len(body) >= _DOC_CHAR_THRESHOLD:
        return True
    h2_count = len(H2_PLUS_RE.findall(body))
    if h2_count >= _DOC_HEADING_COUNT:
        return True
    if body.startswith("# ") and len(body) >= _DOC_H1_CHAR_THRESHOLD:
        return True
    return False


def _slugify(text: str, max_len: int = 60) -> str:
    """Very simple slug — ascii letters, digits, hyphens."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[\s_]+", "-", text)
    return text[:max_len].rstrip("-")


def _strip_blockquote(text: str) -> str:
    """Remove leading '> ' prefix from blockquote lines."""
    lines = []
    for line in text.split("\n"):
        if line.startswith("> "):
            lines.append(line[2:])
        elif line == ">":
            lines.append("")
        else:
            lines.append(line)
    return "\n".join(lines)


def _extract_title(body: str, turn_index: int) -> str:
    working = body

    # Attachment blocks: strip the blockquote wrapper and the "**Attachment: ...**" line
    if body.lstrip().startswith("> **Attachment:"):
        working = _strip_blockquote(body).strip()
        working = ATTACHMENT_HEADER_RE.sub("", working).strip()
        # Skip past a leading --- delimiter (YAML frontmatter or section break)
        if working.startswith("---"):
            working = working.split("---", 2)[-1].strip()

    # 1. Markdown heading
    m = HEADING_RE.search(working)
    if m:
        return m.group(1).strip()

    # 2. YAML title: field
    m = YAML_TITLE_RE.search(working)
    if m:
        return m.group(1).strip().strip("\"'")

    # 3. First non-empty, non-separator line
    for line in working.split("\n"):
        line = line.strip()
        if line and line != "---":
            return line[:80]

    return f"turn-{turn_index}"


def _save_document(output_dir: Path, turn: dict, doc_title: str, seq: int) -> str:
    """Write the document body to a file; return the relative path from output_dir."""
    role_dir = "human" if turn["role"] == "Human" else "claude"
    slug = _slugify(doc_title) or f"turn-{turn['index']}"
    filename = f"{seq:03d}-{slug}.md"
    dest = output_dir / role_dir
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / filename
    author = turn["role"]
    header = f"# {doc_title}\n\n> {author} · {turn['timestamp']} · turn {turn['index']}\n\n"
    path.write_text(header + turn["body"], encoding="utf-8")
    return f"{role_dir}/{filename}"


class Command(BaseCommand):
    help = "Import an exported conversation into an ApertureLog-backed Initiative."

    def add_arguments(self, parser):
        parser.add_argument("file", type=str, help="Path to the conversation export file.")
        parser.add_argument(
            "--group",
            required=True,
            help="Slug of the Group to sponsor the Initiative.",
        )
        parser.add_argument(
            "--platform",
            default="claude",
            choices=["claude", "chatgpt"],
            help="Export platform (default: claude).",
        )
        parser.add_argument(
            "--title",
            default="",
            help="Override the Initiative title. Defaults to the conversation title in the export.",
        )
        parser.add_argument(
            "--author-name",
            default="ml",
            help="authored_by value for Human turns (default: ml).",
        )
        parser.add_argument(
            "--output-dir",
            default="",
            help=(
                "Directory to write extracted document files. "
                "Defaults to <export-stem>-documents/ next to the input file."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and validate without writing to the database or disk.",
        )

    def handle(self, *args, **options):
        export_path = Path(options["file"]).expanduser()
        if not export_path.exists():
            raise CommandError(f"File not found: {export_path}")

        output_dir = (
            Path(options["output_dir"]).expanduser()
            if options["output_dir"]
            else export_path.parent / f"{export_path.stem}-documents"
        )

        # --- Parse ---
        text = export_path.read_text(encoding="utf-8")

        if options["platform"] == "claude":
            try:
                frontmatter, turns = _parse_claude_markdown(text)
            except ValueError as e:
                raise CommandError(str(e))
        else:
            raise CommandError("ChatGPT import not yet implemented.")

        title = options["title"] or frontmatter.get("title", export_path.stem)
        source_url = frontmatter.get("source", "")
        conversation_id = ""
        m = SOURCE_URL_RE.search(source_url)
        if m:
            conversation_id = m.group(1)

        # --- Detect documents ---
        doc_seq = 0
        for turn in turns:
            turn["is_document"] = _is_document(turn["body"], turn["role"])
            if turn["is_document"]:
                doc_seq += 1
                turn["doc_title"] = _extract_title(turn["body"], turn["index"])
                turn["doc_seq"] = doc_seq

        doc_turns = [t for t in turns if t["is_document"]]

        self.stdout.write(
            f"Parsed {len(turns)} turns from '{title}' (platform={options['platform']})\n"
            f"  {len(doc_turns)} turns detected as documents → {output_dir}"
        )

        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS("Dry run — no writes."))
            for t in turns[:5]:
                tag = " [DOC]" if t["is_document"] else ""
                self.stdout.write(
                    f"  [{t['index']:>3}] {t['role']:8s} {t['timestamp']}{tag}: "
                    f"{t['body'][:60].replace(chr(10), ' ')}..."
                )
            if doc_turns:
                self.stdout.write("\nDocuments that would be extracted:")
                for t in doc_turns:
                    self.stdout.write(f"  [{t['index']:>3}] {t['doc_title'][:70]}")
            return

        # --- Resolve group ---
        try:
            group = Group.objects.get(slug=options["group"])
        except Group.DoesNotExist:
            raise CommandError(f"Group not found: {options['group']}")

        group_ct = ContentType.objects.get_for_model(Group)

        # --- Extract documents to disk ---
        doc_filenames: dict[int, str] = {}
        for t in doc_turns:
            filename = _save_document(output_dir, t, t["doc_title"], t["doc_seq"])
            doc_filenames[t["index"]] = filename
            self.stdout.write(f"  Saved: {output_dir / filename}")

        # --- Write to database ---
        with transaction.atomic():
            initiative = Initiative.objects.create(
                title=title,
                status=InitiativeStatus.SIMMERING,
                direction="Imported conversation — curation pending.",
                sponsor_content_type=group_ct,
                sponsor_object_id=group.id,
            )

            log: ApertureLog = initiative.aperture_log
            log.import_source = {
                "platform": options["platform"],
                "conversation_id": conversation_id,
                "title": title,
                "model": frontmatter.get("model", ""),
                "exported": str(frontmatter.get("exported", "")),
                "imported_at": datetime.now(timezone.utc).isoformat(),
                "extracted_documents": len(doc_turns),
                "output_dir": str(output_dir),
            }
            log.save(update_fields=["import_source"])

            ApertureLogEntry.objects.create(
                aperture_log=log,
                kind=ApertureLogEntryKind.LEDGER,
                is_system_generated=True,
                authored_by="system",
                ledger_event_type=LedgerEventType.SESSION_STARTED,
                ledger_data={
                    "source": "import_conversation",
                    "platform": options["platform"],
                    "conversation_id": conversation_id,
                    "turn_count": len(turns),
                    "extracted_documents": len(doc_turns),
                },
            )

            author_name = options["author_name"]
            entries = []
            for turn in turns:
                authored_by = author_name if turn["role"] == "Human" else "claude"
                if turn["is_document"]:
                    filename = doc_filenames[turn["index"]]
                    body = turn["body"]  # full text always preserved
                    ledger_data = {
                        "document_ref": filename,
                        "document_title": turn["doc_title"],
                        "char_count": len(turn["body"]),
                        "output_dir": str(output_dir),
                    }
                else:
                    body = turn["body"]
                    ledger_data = None

                entries.append(
                    ApertureLogEntry(
                        aperture_log=log,
                        kind=ApertureLogEntryKind.PROSE,
                        body=body,
                        authored_by=authored_by,
                        source_turn_index=turn["index"],
                        source_timestamp=turn["parsed_timestamp"],
                        ledger_data=ledger_data,
                    )
                )
            ApertureLogEntry.objects.bulk_create(entries)

            ApertureLogEntry.objects.create(
                aperture_log=log,
                kind=ApertureLogEntryKind.LEDGER,
                is_system_generated=True,
                authored_by="system",
                ledger_event_type=LedgerEventType.SESSION_ENDED,
                ledger_data={"source": "import_conversation"},
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nImported {len(turns)} turns into Initiative {initiative.id}\n"
                f"  Title:         {title}\n"
                f"  Group:         {group.title} ({group.slug})\n"
                f"  Status:        {initiative.status}\n"
                f"  ApertureLog:   {log.id}\n"
                f"  Docs extracted: {len(doc_turns)} → {output_dir}\n"
                f"\nNext: open the Initiative in Atrium and run the curation pass."
            )
        )
