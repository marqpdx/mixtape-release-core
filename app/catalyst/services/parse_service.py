# catalyst/services/parse_service.py
"""
File parsing for Catalyst Stage 3.

parse_file(name, data) → ParsedFile

Supports: .docx, .xlsx, .xls, .csv, .pdf, .md, .txt

Strategy per type:
  xlsx/xls — each non-noise, non-empty sheet → one register;
               row count (minus header) → entry_count;
               first row string values → columns
  csv       — filename → register; first row → columns; row count → entry_count
  docx      — each Heading 1 section → register; table row count → entry_count
  pdf       — filename → register; page/line count as proxy
  md/txt    — each "# Heading" section → register; non-blank lines → entry_count

Confidence:
  high    — entry_count ≥ 5 and columns detected (xlsx/csv) or entry_count ≥ 5 (docx/md)
  medium  — entry_count ≥ 1
  low     — entry_count = 0 or noise sheet name
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass, field
from typing import BinaryIO

logger = logging.getLogger(__name__)

# Sheet/section names that are structural noise, not registers
NOISE_SHEET_NAMES = frozenset({
    "summary", "cover", "cover page", "sheet1", "sheet2", "sheet3",
    "sheet 1", "sheet 2", "sheet 3", "notes", "template", "overview",
    "index", "readme", "todo", "about", "scratch", "draft", "archive",
    "old", "backup", "reference", "changelog", "instructions",
    "key", "legend", "lookup", "data", "info", "help",
})

_CONF_RANK = {"high": 2, "medium": 1, "low": 0}

_SEMANTIC_PROMPT = """\
A file is being imported into a knowledge base for a team event.
File name: "{filename}"

Content preview (may be truncated to first ~4000 characters):
---
{content}
---

Count the distinct named ITEMS in this file. Use common sense about what counts as one item:
- Recipe or menu file → count individual dish names (e.g. "Cashew dill sauce") — NOT ingredient rows, measurements, or quantity cells
- Staff or people file → count individual people by name — NOT their roles, shifts, or contact fields
- Supplier or partner file → count distinct organization names — NOT products they carry or line items
- Meeting notes file → count distinct meeting sessions — NOT individual action items or attendees
- Task or prep list → count distinct named tasks or prep steps

Respond with JSON only — no explanation, no markdown fences:
{{"entity_type": "recipes", "entity_plural": "recipes", "count": 39, "examples": ["Cashew dill sauce", "Root hash", "Beet salad ~est"], "confidence": "high"}}

entity_type must be one of: recipes, people, suppliers, meeting_notes, tasks, documents\
"""


def extract_text_preview(filename: str, data: bytes, max_chars: int = 4000) -> str:
    """Extract a plain-text preview from any supported file type."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    buf = io.BytesIO(data)
    parts: list[str] = []

    try:
        if ext in ("xlsx", "xls"):
            import openpyxl
            wb = openpyxl.load_workbook(buf, read_only=True, data_only=True)
            for sheet_name in wb.sheetnames[:4]:
                ws = wb[sheet_name]
                parts.append(f"[Sheet: {sheet_name}]")
                for row in ws.iter_rows(values_only=True, max_row=80):
                    cells = [str(c) for c in row if c is not None]
                    if cells:
                        parts.append("\t".join(cells))
        elif ext == "csv":
            import csv
            text = data.decode("utf-8", errors="replace")
            for row in list(csv.reader(text.splitlines()))[:120]:
                if any(c.strip() for c in row):
                    parts.append("\t".join(row))
        elif ext == "docx":
            from docx import Document
            doc = Document(buf)
            for p in doc.paragraphs:
                if p.text.strip():
                    parts.append(p.text.strip())
        elif ext == "pdf":
            from pypdf import PdfReader
            reader = PdfReader(buf)
            for page in reader.pages[:6]:
                t = page.extract_text() or ""
                if t.strip():
                    parts.append(t.strip())
        else:
            parts.append(data.decode("utf-8", errors="replace"))
    except Exception:
        parts.append(data[:max_chars].decode("utf-8", errors="replace"))

    return "\n".join(parts)[:max_chars]


def semantic_analyze(
    filename: str,
    data: bytes,
    codex_cwd: str | None = None,
    timeout: int = 45,
) -> dict | None:
    """
    Ask the local Claude Code instance to count distinct named items in a file.
    Returns dict with entity_type, entity_plural, count, examples, confidence — or None on failure.
    Falls back gracefully; never raises.
    """
    claude_bin = shutil.which("claude") or os.getenv("CLAUDE_CODE_PATH", "claude")

    text_preview = extract_text_preview(filename, data)
    if not text_preview.strip():
        return None

    prompt = _SEMANTIC_PROMPT.format(filename=filename, content=text_preview)

    # Write prompt to a temp file to avoid shell quoting issues with long content
    tmp_prompt = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(prompt)
            tmp_prompt = f.name

        result = subprocess.run(
            [claude_bin, "-p", "--dangerously-skip-permissions", prompt],
            cwd=codex_cwd or os.getcwd(),
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            logger.warning("[catalyst] claude -p returned %s for %s: %s", result.returncode, filename, result.stderr[:200])
            return None

        raw = result.stdout.strip()
        if not raw:
            return None

        # Try direct parse first, then extract first JSON object
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if not m:
                logger.warning("[catalyst] no JSON in claude response for %s: %r", filename, raw[:300])
                return None
            parsed = json.loads(m.group())

        # Validate required fields
        if not isinstance(parsed.get("count"), int):
            return None

        return {
            "entity_type": str(parsed.get("entity_type", "documents")),
            "entity_plural": str(parsed.get("entity_plural", "records")),
            "count": max(0, int(parsed["count"])),
            "examples": list(parsed.get("examples", []))[:5],
            "confidence": str(parsed.get("confidence", "medium")),
        }

    except subprocess.TimeoutExpired:
        logger.warning("[catalyst] claude -p timed out for %s", filename)
        return None
    except Exception as exc:
        logger.warning("[catalyst] semantic_analyze failed for %s: %s", filename, exc)
        return None
    finally:
        if tmp_prompt:
            try:
                os.unlink(tmp_prompt)
            except OSError:
                pass


@dataclass
class ProposedRegister:
    slug: str
    display_name: str
    entry_count: int
    source_file: str
    canon_synonym: str = "Canon"
    notes: str = ""
    confidence: str = "medium"     # "high" | "medium" | "low"
    columns: list = field(default_factory=list)  # detected column headers (first 8)


@dataclass
class ParsedFile:
    filename: str
    file_type: str
    registers: list   # list[ProposedRegister]
    skipped: list     # list[str] — sheet/section names that were noise-blocked
    file_notes: str = ""


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_]+", "-", text)[:64]


def _confidence(entry_count: int, columns: list) -> str:
    if entry_count >= 5 and columns:
        return "high"
    if entry_count >= 5:
        return "high"
    if entry_count >= 1:
        return "medium"
    return "low"


def _confidence_doc(entry_count: int) -> str:
    if entry_count >= 5:
        return "high"
    if entry_count >= 1:
        return "medium"
    return "low"


def parse_file(filename: str, data: bytes | BinaryIO) -> ParsedFile:
    if isinstance(data, bytes):
        data = io.BytesIO(data)

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    base = filename.rsplit(".", 1)[0] if "." in filename else filename

    if ext in ("xlsx", "xls"):
        return _parse_xlsx(filename, base, ext, data)
    if ext == "csv":
        return _parse_csv(filename, base, data)
    if ext == "docx":
        return _parse_docx(filename, base, data)
    if ext == "pdf":
        return _parse_pdf(filename, base, data)
    if ext in ("md", "txt"):
        return _parse_text(filename, base, ext, data)

    return ParsedFile(
        filename=filename,
        file_type=ext or "unknown",
        registers=[ProposedRegister(
            slug=slugify(base),
            display_name=base,
            entry_count=0,
            source_file=filename,
            confidence="low",
            notes="Unknown file type — manual review required",
        )],
        skipped=[],
        file_notes="Unknown file type",
    )


# ── xlsx / xls ────────────────────────────────────────────────────────────────

def _parse_xlsx(filename: str, base: str, ext: str, data: BinaryIO) -> ParsedFile:
    import openpyxl
    try:
        wb = openpyxl.load_workbook(data, read_only=True, data_only=True)
    except Exception as exc:
        return ParsedFile(
            filename=filename,
            file_type=ext,
            registers=[ProposedRegister(
                slug=slugify(base), display_name=base, entry_count=0,
                source_file=filename, confidence="low",
                notes=f"Could not open workbook: {exc}",
            )],
            skipped=[],
            file_notes=f"Error opening workbook: {exc}",
        )

    registers = []
    skipped = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        non_empty = [r for r in rows if any(c is not None for c in r)]

        if not non_empty:
            skipped.append(f"{sheet_name} (empty)")
            continue

        if sheet_name.lower().strip() in NOISE_SHEET_NAMES:
            skipped.append(f"{sheet_name} (noise)")
            continue

        # Column detection — first row as header if values are mostly strings
        first_row = non_empty[0]
        candidate_cols = [str(c).strip() for c in first_row if c is not None]
        str_count = sum(1 for c in first_row if isinstance(c, str) and c.strip())
        non_null_count = sum(1 for c in first_row if c is not None)
        is_header = non_null_count >= 2 and str_count >= (non_null_count * 0.6)
        columns = candidate_cols[:8] if is_header else []

        entry_count = max(0, len(non_empty) - (1 if is_header else 0))
        conf = _confidence(entry_count, columns)

        notes_parts = []
        if columns:
            notes_parts.append(f"columns: {', '.join(columns[:6])}")

        registers.append(ProposedRegister(
            slug=slugify(sheet_name),
            display_name=sheet_name,
            entry_count=entry_count,
            source_file=filename,
            confidence=conf,
            columns=columns,
            notes="; ".join(notes_parts),
        ))

    if not registers:
        registers.append(ProposedRegister(
            slug=slugify(base), display_name=base, entry_count=0,
            source_file=filename, confidence="low",
            notes="Workbook appears empty or all sheets were noise",
        ))

    skip_note = f"{len(skipped)} sheet{'s' if len(skipped) != 1 else ''} skipped" if skipped else ""
    return ParsedFile(
        filename=filename,
        file_type=ext,
        registers=registers,
        skipped=skipped,
        file_notes=skip_note,
    )


# ── csv ───────────────────────────────────────────────────────────────────────

def _parse_csv(filename: str, base: str, data: BinaryIO) -> ParsedFile:
    import csv
    text = data.read().decode("utf-8", errors="replace")
    rows = list(csv.reader(text.splitlines()))
    non_empty = [r for r in rows if any(c.strip() for c in r)]

    columns = []
    if non_empty:
        first_row = non_empty[0]
        str_cells = [c.strip() for c in first_row if c.strip()]
        numeric_count = sum(1 for c in str_cells if c.replace(".", "").replace("-", "").isdigit())
        is_header = len(str_cells) >= 2 and numeric_count < len(str_cells) * 0.5
        columns = str_cells[:8] if is_header else []

    entry_count = max(0, len(non_empty) - (1 if columns else 0))
    conf = _confidence(entry_count, columns)

    return ParsedFile(
        filename=filename,
        file_type="csv",
        registers=[ProposedRegister(
            slug=slugify(base),
            display_name=base,
            entry_count=entry_count,
            source_file=filename,
            confidence=conf,
            columns=columns,
        )],
        skipped=[],
    )


# ── docx ──────────────────────────────────────────────────────────────────────

def _parse_docx(filename: str, base: str, data: BinaryIO) -> ParsedFile:
    from docx import Document
    try:
        doc = Document(data)
    except Exception as exc:
        return ParsedFile(
            filename=filename,
            file_type="docx",
            registers=[ProposedRegister(
                slug=slugify(base), display_name=base, entry_count=0,
                source_file=filename, confidence="low",
                notes=f"Could not open document: {exc}",
            )],
            skipped=[],
            file_notes=f"Error opening document: {exc}",
        )

    sections: list[tuple[str, int]] = []
    current_heading: str | None = None
    current_count = 0

    def flush():
        nonlocal current_heading, current_count
        if current_heading is not None:
            sections.append((current_heading, current_count))
        current_heading = None
        current_count = 0

    for block in doc.element.body:
        tag = block.tag.split("}")[-1] if "}" in block.tag else block.tag
        if tag == "p":
            from docx.oxml.ns import qn
            style_el = block.find(qn("w:pStyle"), block.nsmap if hasattr(block, "nsmap") else {})
            style_val = style_el.get(
                "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val", ""
            ) if style_el is not None else ""
            text = "".join(n.text or "" for n in block.iter()
                           if n.tag.endswith("}t")).strip()
            if style_val in ("Heading1", "1", "Heading 1") or re.match(r"^heading.?1$", style_val, re.I):
                flush()
                current_heading = text or base
            elif text:
                current_count += 1
        elif tag == "tbl":
            rows = block.findall(
                ".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tr"
            )
            current_count += max(0, len(rows) - 1)

    flush()

    if not sections:
        total_rows = sum(max(0, len(t.rows) - 1) for t in doc.tables)
        para_count = len([p for p in doc.paragraphs if p.text.strip()])
        sections = [(base, total_rows or para_count)]
        file_notes = "No Heading 1 sections — treated as single register"
    else:
        file_notes = f"{len(sections)} Heading 1 section{'s' if len(sections) != 1 else ''}"

    registers = [
        ProposedRegister(
            slug=slugify(name),
            display_name=name,
            entry_count=count,
            source_file=filename,
            confidence=_confidence_doc(count),
            notes=f"Heading 1 section · {count} content rows" if count else "Heading 1 section · no rows detected",
        )
        for name, count in sections
        if name.strip()
    ]

    return ParsedFile(
        filename=filename,
        file_type="docx",
        registers=registers,
        skipped=[],
        file_notes=file_notes,
    )


# ── pdf ───────────────────────────────────────────────────────────────────────

def _parse_pdf(filename: str, base: str, data: BinaryIO) -> ParsedFile:
    try:
        from pypdf import PdfReader
        reader = PdfReader(data)
        page_count = len(reader.pages)
        line_count = 0
        for page in reader.pages:
            text = page.extract_text() or ""
            line_count += len([ln for ln in text.splitlines() if ln.strip()])
        entry_count = line_count or page_count
        file_notes = f"{page_count} page{'s' if page_count != 1 else ''}"
    except Exception:
        entry_count = 0
        file_notes = "PDF parse error — could not extract text"

    return ParsedFile(
        filename=filename,
        file_type="pdf",
        registers=[ProposedRegister(
            slug=slugify(base),
            display_name=base,
            entry_count=entry_count,
            source_file=filename,
            confidence="medium",
            notes="PDF — entry count is line-based estimate",
        )],
        skipped=[],
        file_notes=file_notes,
    )


# ── md / txt ─────────────────────────────────────────────────────────────────

def _parse_text(filename: str, base: str, ext: str, data: BinaryIO) -> ParsedFile:
    text = data.read().decode("utf-8", errors="replace")
    lines = text.splitlines()

    sections: list[tuple[str, int]] = []
    current_heading: str | None = None
    current_count = 0

    def flush():
        nonlocal current_heading, current_count
        if current_heading is not None:
            sections.append((current_heading, current_count))
        current_heading = None
        current_count = 0

    for line in lines:
        if re.match(r"^# ", line):
            flush()
            current_heading = line[2:].strip()
        elif line.strip():
            current_count += 1

    flush()

    if not sections:
        non_blank = len([ln for ln in lines if ln.strip()])
        sections = [(base, non_blank)]
        file_notes = "No # headings — treated as single register"
    else:
        file_notes = f"{len(sections)} heading section{'s' if len(sections) != 1 else ''}"

    registers = [
        ProposedRegister(
            slug=slugify(name),
            display_name=name,
            entry_count=count,
            source_file=filename,
            confidence=_confidence_doc(count),
        )
        for name, count in sections
        if name.strip()
    ]

    return ParsedFile(
        filename=filename,
        file_type=ext,
        registers=registers,
        skipped=[],
        file_notes=file_notes,
    )
