# catalyst/services/parse_service.py
"""
File parsing for Catalyst Stage 3.

parse_file(name, data) → list[ProposedRegister]

Supports: .docx, .xlsx, .xls, .csv, .pdf, .md, .txt
Strategy per type:
  xlsx/xls — each non-empty sheet → one register; row count (minus header) → entry_count
  csv       — filename → register name; row count (minus header) → entry_count
  docx      — each top-level Heading 1 (or file-level fallback) → register;
               table row count within that section → entry_count
  pdf       — filename → register; page count as proxy entry_count
  md/txt    — each "# Heading" → register; non-blank lines below → entry_count
"""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field
from typing import BinaryIO


@dataclass
class ProposedRegister:
    slug: str
    display_name: str
    entry_count: int
    source_file: str
    canon_synonym: str = "Canon"
    notes: str = ""


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_]+", "-", text)[:64]


def parse_file(filename: str, data: bytes | BinaryIO) -> list[ProposedRegister]:
    if isinstance(data, bytes):
        data = io.BytesIO(data)

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    base = filename.rsplit(".", 1)[0] if "." in filename else filename

    if ext in ("xlsx", "xls"):
        return _parse_xlsx(filename, base, data)
    if ext == "csv":
        return _parse_csv(filename, base, data)
    if ext == "docx":
        return _parse_docx(filename, base, data)
    if ext == "pdf":
        return _parse_pdf(filename, base, data)
    if ext in ("md", "txt"):
        return _parse_text(filename, base, data)

    return [ProposedRegister(
        slug=slugify(base),
        display_name=base,
        entry_count=0,
        source_file=filename,
        notes="Unknown file type — manual review required",
    )]


# ── xlsx / xls ────────────────────────────────────────────────────────────────

def _parse_xlsx(filename: str, base: str, data: BinaryIO) -> list[ProposedRegister]:
    import openpyxl
    try:
        wb = openpyxl.load_workbook(data, read_only=True, data_only=True)
    except Exception as exc:
        return [ProposedRegister(
            slug=slugify(base), display_name=base, entry_count=0,
            source_file=filename, notes=f"Could not open workbook: {exc}",
        )]

    results = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        non_empty = [r for r in rows if any(c is not None for c in r)]
        if not non_empty:
            continue
        entry_count = max(0, len(non_empty) - 1)
        results.append(ProposedRegister(
            slug=slugify(sheet_name),
            display_name=sheet_name,
            entry_count=entry_count,
            source_file=filename,
        ))

    if not results:
        results.append(ProposedRegister(
            slug=slugify(base), display_name=base, entry_count=0,
            source_file=filename, notes="Workbook appears empty",
        ))
    return results


# ── csv ───────────────────────────────────────────────────────────────────────

def _parse_csv(filename: str, base: str, data: BinaryIO) -> list[ProposedRegister]:
    import csv
    text = data.read().decode("utf-8", errors="replace")
    rows = list(csv.reader(text.splitlines()))
    entry_count = max(0, len([r for r in rows if any(c.strip() for c in r)]) - 1)
    return [ProposedRegister(
        slug=slugify(base),
        display_name=base,
        entry_count=entry_count,
        source_file=filename,
    )]


# ── docx ──────────────────────────────────────────────────────────────────────

def _parse_docx(filename: str, base: str, data: BinaryIO) -> list[ProposedRegister]:
    from docx import Document
    try:
        doc = Document(data)
    except Exception as exc:
        return [ProposedRegister(
            slug=slugify(base), display_name=base, entry_count=0,
            source_file=filename, notes=f"Could not open document: {exc}",
        )]

    # Collect heading-1 sections; count non-heading paragraphs + table rows within each
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
        # No heading-1 found — treat whole doc as one register
        total_rows = sum(
            max(0, len(t.rows) - 1) for t in doc.tables
        )
        para_count = len([p for p in doc.paragraphs if p.text.strip()])
        sections = [(base, total_rows or para_count)]

    return [
        ProposedRegister(
            slug=slugify(name),
            display_name=name,
            entry_count=count,
            source_file=filename,
        )
        for name, count in sections
        if name.strip()
    ]


# ── pdf ───────────────────────────────────────────────────────────────────────

def _parse_pdf(filename: str, base: str, data: BinaryIO) -> list[ProposedRegister]:
    try:
        from pypdf import PdfReader
        reader = PdfReader(data)
        page_count = len(reader.pages)
        # Extract text to estimate line/entry count
        line_count = 0
        for page in reader.pages:
            text = page.extract_text() or ""
            line_count += len([l for l in text.splitlines() if l.strip()])
        entry_count = line_count or page_count
    except Exception:
        entry_count = 0

    return [ProposedRegister(
        slug=slugify(base),
        display_name=base,
        entry_count=entry_count,
        source_file=filename,
        notes="PDF parsed — entry count is line-based estimate",
    )]


# ── md / txt ─────────────────────────────────────────────────────────────────

def _parse_text(filename: str, base: str, data: BinaryIO) -> list[ProposedRegister]:
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
        non_blank = len([l for l in lines if l.strip()])
        sections = [(base, non_blank)]

    return [
        ProposedRegister(
            slug=slugify(name),
            display_name=name,
            entry_count=count,
            source_file=filename,
        )
        for name, count in sections
        if name.strip()
    ]
