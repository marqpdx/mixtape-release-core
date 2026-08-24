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
import unicodedata
from dataclasses import dataclass, field
from typing import BinaryIO

from claude import service as claude_service

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

# Shape-derived parent→child relationships per vertical.
# When a declared type is absent but is a known child of an aligned declared type,
# it is nested inside those files (not truly absent) and will be found in Phase 2 extraction.
VERTICAL_SHAPE_CHILDREN: dict[str, dict[str, list[str]]] = {
    "food-service": {
        "recipe":    ["ingredient", "instruction step", "storage guidance", "costing note"],
        "menu":      ["recipe"],
    },
    "retail": {
        "product":   ["product variant", "variant"],
        "category":  ["product"],
        "collection": ["product"],
    },
    "education": {
        "course":    ["learning objective", "competency", "assessment"],
        "rubric":    ["competency"],
        "syllabus":  ["learning objective"],
    },
}


def _detect_vertical(general_context: str) -> str | None:
    """Read 'VERTICAL: food-service' from the first line of general_context."""
    for line in general_context.splitlines():
        m = re.match(r"^VERTICAL:\s*(\S+)", line.strip())
        if m:
            return m.group(1).lower()
    return None


_CLIENT_CONTEXT_FALLBACK = """\
No client vocabulary provided. Use general knowledge to classify and count.\
"""

_SEMANTIC_PROMPT = """\
You are analyzing a file being imported into a knowledge base.

--- CLIENT VOCABULARY (use this to determine what counts as one item) ---
{client_context}
--- END CLIENT VOCABULARY ---

FILE NAME: {filename}
CONTENT PREVIEW (headings listed first, then body content):
---
{content}
---

INSTRUCTIONS:

1. READ the client vocabulary above first. The client has named the things that matter to them.
   Their definitions override any general assumption about what to count.
   If the client says "Recipe = a named dish with instructions and an outcome", then a Recipe is
   a named dish — NOT a meal occasion, NOT an ingredient line, NOT a section heading.

2. CLASSIFY this file into the entity type that best matches the client's vocabulary:
   - If the client defines Recipes as named dishes: look for individual dish names in overview
     lines, section descriptions, or recipe headings — NOT the date/session headings that bundle them.
   - If the client defines Meals as time-based bundles of Recipes: Meals are containers, not atoms.
     A "Wednesday Lunch" heading is a Meal, but the dishes inside it (quinoa salad, grilled chicken)
     are Recipes. Count Recipes, not Meal headings, unless the client's primary interest is scheduling.
   - If the client defines People as staff and volunteers: count distinct named individuals only —
     skip blank rows, phone-number rows, role labels, header rows.
   - If the client defines Purveyors as ingredient suppliers or sponsors: count confirmed/contracted
     organizations from a "Confirmed Partners" or equivalent sheet — NOT prospect/outreach lists.
   - If the file contains something the client did not mention (meeting notes, schedules, dietary
     restrictions): classify it as an unexpected type and note it clearly.

KEY RULE — COUNT ATOMIC ENTITIES, NOT CONTAINERS:
The client's vocabulary lists entity types in order of importance. Recipes are the primary
unit of interest. A file that IS a Menu (container of Recipes) or a Menu Meeting (discussion
of Recipes) should yield a RECIPE count — count the named dishes inside it, not the number
of menus or meetings. A file with "Wednesday Dinner", "Thursday Lunch" as headings contains
MEALS (containers), and RECIPES (dishes) inside each meal. Count Recipes — the named individual
dishes listed under those headings. Never return count=1 for a document that clearly contains
many distinct items. If unsure whether a line is a recipe name or a heading, count it as a recipe.

3. COUNT the items, following these rules:
   • NEVER count: column headers, True/False values, phone numbers, email addresses, URLs,
     blank cells, numeric IDs, section labels, or row numbers.
   • For xlsx with multiple sheets: count only sheets relevant to the entity type; do not
     double-count across sheets.
   • Examples must be real item names (actual dish names, person names, org names) —
     never True/False, never a URL, never a role label like "Lead" or "Volunteer".
   • If this file looks like a duplicate of another file already seen, say so in notes.

4. If the client provided entity expectations, report how your findings align:
   - Which expected types were found and with what counts
   - Which expected types were NOT found in this file (note as absent, not zero)
   - Any unexpected types found that the client did not mention

Respond with JSON only — no explanation, no markdown fences:
{{"entity_type": "recipes", "entity_plural": "recipes", "count": 34, \
"examples": ["Cashew dill sauce", "Grilled chicken", "Cold quinoa salad"], \
"confidence": "high", \
"notes": "Counted named dishes from Overview lines across all meal sections, plus named recipes \
from the prep/sauce sections. Did not count meal-occasion headings (those are Meals, not Recipes). \
Did not count ingredients. Client expected: Recipes ✓ found, Ingredients not directly listed, \
Menus (container) present as structure only."}}

confidence: "high" (clear, certain), "medium" (some ambiguity), "low" (noisy file, best estimate)\
"""

_CHUNK_SEMANTIC_PROMPT = """\
You are analyzing CHUNK {chunk_num} of {chunk_total} from a file being imported into a knowledge base.
Count only what you see in THIS CHUNK — do not estimate for the whole file.

--- CLIENT VOCABULARY ---
{client_context}
--- END CLIENT VOCABULARY ---

FILE: {filename}  (chunk {chunk_num}/{chunk_total})
CHUNK CONTENT:
---
{content}
---

INSTRUCTIONS:
Count distinct named items visible IN THIS CHUNK ONLY. Same rules apply:
- Recipes/dishes: look for dish names ("Cashew Dill Sauce", "Root Hash", "Dahl Soup") —
  NOT meal-occasion headings ("Wednesday Dinner"), NOT ingredient lines, NOT action items.
  Lines ending in "-" often mark recipe names in chef notebooks — treat them as dish names.
- People: distinct named individuals only; skip roles, email addresses, phone numbers.
- Suppliers: confirmed organization names only; skip prospects and outreach lists.
If this chunk contains only logistics, quantities, preamble, or action items with no
named entities of the client's types, return count: 0.

Respond with JSON only:
{{"entity_type": "...", "entity_plural": "...", "count": N, \
"examples": ["name1", "name2"], "confidence": "high|medium|low", "notes": "..."}}
"""

_CHUNK_FULL_TEXT_MAX = 30_000   # chars to extract before chunking (covers most real-world files)
_CHUNK_SIZE = 5_000             # chars per chunk
_CHUNK_OVERLAP = 300            # char overlap between consecutive chunks


def _chunk_text(text: str) -> list[str]:
    """Split text into overlapping chunks of _CHUNK_SIZE chars."""
    if len(text) <= _CHUNK_SIZE:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        chunks.append(text[start:start + _CHUNK_SIZE])
        start += _CHUNK_SIZE - _CHUNK_OVERLAP
    return chunks


def _parse_semantic_json(raw: str, filename: str) -> dict | None:
    """Parse a Claude semantic-analysis JSON response into a result dict."""
    try:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if not m:
                logger.warning("[catalyst] no JSON in semantic response for %s: %r", filename, raw[:200])
                return None
            parsed = json.loads(m.group())
        if not isinstance(parsed.get("count"), int):
            return None
        doc_type = parsed.get("document_type", "")
        entity_type = parsed.get("entity_type") or parsed.get("entity_label") or doc_type.lower() or "records"
        entity_plural = parsed.get("entity_plural") or entity_type + "s"
        return {
            "entity_type": str(entity_type),
            "entity_plural": str(entity_plural),
            "count": max(0, int(parsed["count"])),
            "examples": list(parsed.get("examples", []))[:5],
            "confidence": str(parsed.get("confidence", "medium")),
            "notes": str(parsed.get("notes", "")),
        }
    except Exception as exc:
        logger.warning("[catalyst] semantic JSON parse failed for %s: %s", filename, exc)
        return None


def _aggregate_chunk_results(results: list[dict], filename: str) -> dict | None:
    """Merge per-chunk semantic results into a single result."""
    results = [r for r in results if r]
    if not results:
        return None
    if len(results) == 1:
        return results[0]

    from collections import Counter
    entity_type = Counter(r["entity_type"] for r in results).most_common(1)[0][0]
    entity_plural = next(
        (r["entity_plural"] for r in results if r["entity_type"] == entity_type),
        entity_type + "s",
    )
    total_count = sum(r["count"] for r in results)

    seen: set[str] = set()
    examples: list[str] = []
    for r in results:
        for ex in r.get("examples", []):
            key = ex.lower().strip()
            if key not in seen and len(examples) < 8:
                seen.add(key)
                examples.append(ex)

    conf_rank = {"high": 2, "medium": 1, "low": 0}
    confidence = min(results, key=lambda r: conf_rank.get(r["confidence"], 1))["confidence"]
    notes = results[0].get("notes", "")
    notes += f" [chunked: {len(results)} passes, counts summed]"

    logger.info("[catalyst] aggregate %s: %s count=%d from %d chunks", filename, entity_type, total_count, len(results))
    return {
        "entity_type": entity_type,
        "entity_plural": entity_plural,
        "count": total_count,
        "examples": examples[:5],
        "confidence": confidence,
        "notes": notes,
    }


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
            for table in doc.tables:
                for row in table.rows:
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if cells:
                        parts.append("\t".join(cells))
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


def _sample_list_items(md: str, max_per_block: int = 4) -> str:
    """
    Keep up to max_per_block bullet items per contiguous list block, then drop
    the rest. Recipe/menu docs are dominated by ingredient lists; sampling instead
    of stripping gives Claude a few ingredient examples per recipe (for ingredient
    detection and counting) while still compressing a 9000-char file to ~2500 chars.
    """
    lines = []
    block_count = 0
    in_block = False
    for line in md.splitlines():
        s = line.strip()
        is_bullet = s.startswith("- ") or s.startswith("* ") or s.startswith("\t- ")
        if is_bullet:
            if not in_block:
                in_block = True
                block_count = 0
            block_count += 1
            if block_count <= max_per_block:
                lines.append(line)
            elif block_count == max_per_block + 1:
                lines.append("  (… more)")
        else:
            in_block = False
            block_count = 0
            lines.append(line)
    return "\n".join(lines)


def _docx_to_markdown(data: bytes) -> str:
    """Convert docx bytes to markdown via mammoth. Falls back to empty string on failure."""
    try:
        import mammoth
        buf = io.BytesIO(data)
        result = mammoth.convert_to_markdown(buf)
        return result.value or ""
    except Exception:
        return ""


def _extract_heading_priority(filename: str, data: bytes, max_chars: int = 8000) -> str:
    """
    For docx: convert to markdown via mammoth, then extract headings first + first paragraph
    per section (overview lines), then remaining body up to max_chars.
    For other types: delegate to extract_text_preview.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext != "docx":
        return extract_text_preview(filename, data, max_chars)

    md = _docx_to_markdown(data)
    if not md.strip():
        # mammoth failed — fall back to python-docx paragraph extraction
        try:
            from docx import Document
            buf = io.BytesIO(data)
            doc = Document(buf)
            lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            return "\n".join(lines)[:max_chars]
        except Exception:
            return extract_text_preview(filename, data, max_chars)

    # Sample bullet-point lists — keep first 4 items per block so Claude sees
    # ingredient examples per recipe while still compressing the file.
    stripped = _sample_list_items(md)

    if len(stripped) <= max_chars:
        return stripped

    # Still over cap after stripping — very large file. Send what we can.
    logger.warning("[catalyst] docx content still %d chars after stripping for %s — truncating to %d", len(stripped), filename, max_chars)
    return stripped[:max_chars]


def semantic_analyze(
    filename: str,
    data: bytes,
    codex_cwd: str | None = None,
    timeout: int = 90,
    client_context: str | None = None,
) -> dict | None:
    """
    Count distinct named items in a file using the local Claude Code instance.

    Short files (≤ _CHUNK_SIZE chars): single-pass analysis.
    Long flat files (> _CHUNK_SIZE): split into overlapping chunks, analyze each,
    aggregate counts and examples. This avoids the 8000-char truncation that
    previously hid recipe cards deep in meeting-notes documents.

    Returns dict with entity_type, entity_plural, count, examples, confidence, notes.
    Falls back gracefully; never raises.
    """
    logger.info("[catalyst] semantic_analyze: file=%s", filename)

    if len(data) > 500_000:
        logger.warning("[catalyst] %s is %d bytes — too large for semantic analysis, skipping", filename, len(data))
        return {"entity_type": "records", "entity_plural": "records", "count": 0,
                "examples": [], "confidence": "low",
                "notes": f"File too large ({len(data)//1024}KB) — split into smaller files or import manually."}

    # Extract up to _CHUNK_FULL_TEXT_MAX chars so chunking can see the whole document.
    full_text = _extract_heading_priority(filename, data, max_chars=_CHUNK_FULL_TEXT_MAX)
    if not full_text.strip():
        return None

    ctx = client_context.strip() if client_context and client_context.strip() else _CLIENT_CONTEXT_FALLBACK
    chunks = _chunk_text(full_text)

    if len(chunks) == 1:
        # Single-pass — original behaviour
        prompt = _SEMANTIC_PROMPT.format(filename=filename, content=full_text, client_context=ctx)
        raw = claude_service.run_blocking(prompt, cwd=codex_cwd or os.getcwd(), timeout=timeout)
        if not raw:
            return None
        result = _parse_semantic_json(raw, filename)
        if result:
            logger.info("[catalyst] semantic result: %s → %s count=%d", filename, result["entity_type"], result["count"])
        return result

    # Multi-pass chunked analysis
    logger.info("[catalyst] semantic_analyze chunking %s: %d chunks (%d chars total)", filename, len(chunks), len(full_text))
    chunk_results: list[dict] = []
    for i, chunk in enumerate(chunks, 1):
        prompt = _CHUNK_SEMANTIC_PROMPT.format(
            chunk_num=i, chunk_total=len(chunks),
            filename=filename, content=chunk, client_context=ctx,
        )
        raw = claude_service.run_blocking(prompt, cwd=codex_cwd or os.getcwd(), timeout=timeout)
        if not raw:
            logger.warning("[catalyst] chunk %d/%d got no response for %s", i, len(chunks), filename)
            continue
        result = _parse_semantic_json(raw, filename)
        if result:
            logger.info("[catalyst] chunk %d/%d: %s count=%d", i, len(chunks), result["entity_type"], result["count"])
            chunk_results.append(result)

    return _aggregate_chunk_results(chunk_results, filename)


_EXTRACT_PROMPT = """\
You are a data extraction assistant. A file has been provided below.

File: {filename}
Entity type to extract: {entity_type} ({entity_plural})

{client_context_block}

Your task: extract every distinct {entity_type} you can identify from this content.

Return a JSON array (not an object) where each element represents one {entity_type}.
Each element MUST have a "name" key. Add any other fields that are naturally present
in the content (e.g. ingredients, description, role, contact, amount, category).

If the client context says a {entity_type} should include child entities (e.g. a recipe
includes an ingredients list), extract those child fields too — use the field name from
the client context. Do not invent fields not in the source. Do not add commentary outside the JSON.

Example shape (fields will vary by content):
[
  {{"name": "Example Item", "field1": "value", "field2": "value"}},
  ...
]

File content:
{content}
"""

_EXTRACT_CHUNK_PROMPT = """\
You are a data extraction assistant. You are analyzing CHUNK {chunk_num} of {chunk_total} from a file.
Extract ONLY the {entity_type} ({entity_plural}) visible in THIS CHUNK — do not estimate for the whole file.

File: {filename}  (chunk {chunk_num}/{chunk_total})

{client_context_block}

Return a JSON array where each element has at minimum a "name" key. Include child fields
(e.g. ingredients for a recipe) if visible in this chunk. Do not add commentary outside the JSON.
Return an empty array [] if this chunk contains no {entity_type} instances.

Chunk content:
{content}
"""

_EXTRACT_CONTEXT_BLOCK = "Client context: {client_context}"


def _parse_entity_json(raw: str, filename: str) -> list[dict]:
    """Parse a Claude entity-extraction JSON array response."""
    try:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r'\[.*\]', raw, re.DOTALL)
            if not m:
                logger.warning("[catalyst] no JSON array in extract response for %s: %r", filename, raw[:300])
                return []
            parsed = json.loads(m.group())
        if not isinstance(parsed, list):
            return []
        return [e for e in parsed if isinstance(e, dict) and e.get("name")]
    except Exception as exc:
        logger.warning("[catalyst] entity JSON parse failed for %s: %s", filename, exc)
        return []


def _run_extract_on_text(
    text: str,
    filename: str,
    entity_type: str,
    entity_plural: str,
    codex_cwd: str | None,
    client_context: str | None,
    timeout: int,
    chunk_info: str | None = None,
) -> list[dict]:
    """Run the extract prompt on pre-extracted text. Used by both single-pass and chunked paths."""
    ctx_block = _EXTRACT_CONTEXT_BLOCK.format(client_context=client_context.strip()) if client_context else ""
    if chunk_info:
        chunk_num, chunk_total = (int(x) for x in chunk_info.split("/"))
        prompt = _EXTRACT_CHUNK_PROMPT.format(
            filename=filename,
            entity_type=entity_type,
            entity_plural=entity_plural,
            client_context_block=ctx_block,
            content=text,
            chunk_num=chunk_num,
            chunk_total=chunk_total,
        )
    else:
        prompt = _EXTRACT_PROMPT.format(
            filename=filename,
            entity_type=entity_type,
            entity_plural=entity_plural,
            client_context_block=ctx_block,
            content=text,
        )
    raw = claude_service.run_blocking(prompt, cwd=codex_cwd or os.getcwd(), timeout=timeout)
    return _parse_entity_json(raw, filename) if raw else []


def extract_entities(
    filename: str,
    data: bytes,
    entity_type: str,
    entity_plural: str,
    codex_cwd: str | None = None,
    client_context: str | None = None,
    timeout: int = 240,
) -> list[dict]:
    """
    Ask Claude to extract every named entity of entity_type from the file.
    Returns a list of dicts, each with at least a 'name' key.
    Returns [] on failure or timeout. For long files, use extract_entities_chunked.
    """
    logger.info("[catalyst] extract_entities: %s → %s from %s", entity_type, entity_plural, filename)

    if len(data) > 500_000:
        logger.warning("[catalyst] %s too large for extraction (%dKB) — skipping", filename, len(data) // 1024)
        return []

    text = _extract_heading_priority(filename, data, max_chars=10_000)
    if not text.strip():
        return []

    entities = _run_extract_on_text(text, filename, entity_type, entity_plural, codex_cwd, client_context, timeout)
    logger.info("[catalyst] extract_entities: %d %s from %s", len(entities), entity_plural, filename)
    return entities


def extract_entities_chunked(
    filename: str,
    data: bytes,
    entity_type: str,
    entity_plural: str,
    codex_cwd: str | None = None,
    client_context: str | None = None,
    timeout_per_chunk: int = 180,
) -> list[dict]:
    """
    Like extract_entities but handles long flat files by chunking.
    Extracts up to _CHUNK_FULL_TEXT_MAX chars, splits into _CHUNK_SIZE-char overlapping
    chunks, runs a separate Claude pass per chunk, deduplicates results by name.
    """
    logger.info("[catalyst] extract_entities_chunked: %s → %s from %s", entity_type, entity_plural, filename)

    if len(data) > 500_000:
        logger.warning("[catalyst] %s too large for chunked extraction — skipping", filename)
        return []

    full_text = _extract_heading_priority(filename, data, max_chars=_CHUNK_FULL_TEXT_MAX)
    if not full_text.strip():
        return []

    chunks = _chunk_text(full_text)
    if len(chunks) == 1:
        entities = _run_extract_on_text(full_text, filename, entity_type, entity_plural, codex_cwd, client_context, timeout_per_chunk)
        logger.info("[catalyst] extract_entities_chunked (single pass): %d %s from %s", len(entities), entity_plural, filename)
        return entities

    all_entities: list[dict] = []
    seen: set[str] = set()
    for i, chunk in enumerate(chunks, 1):
        chunk_entities = _run_extract_on_text(
            chunk, filename, entity_type, entity_plural, codex_cwd, client_context,
            timeout_per_chunk, chunk_info=f"{i}/{len(chunks)}",
        )
        for e in chunk_entities:
            key = e.get("name", "").lower().strip()
            if key and key not in seen:
                seen.add(key)
                all_entities.append(e)
        logger.info("[catalyst] chunk %d/%d: %d new %s (total %d)", i, len(chunks), len(chunk_entities), entity_plural, len(all_entities))

    logger.info("[catalyst] extract_entities_chunked: %d %s total from %s (%d chunks)", len(all_entities), entity_plural, filename, len(chunks))
    return all_entities


def format_entities_as_markdown(entity_plural: str, entities: list[dict]) -> str:
    """
    Format a list of extracted entity dicts as a markdown Entries section body.
    Each entity gets a ### heading for its name, then bullet lines for other fields.
    List fields (e.g. ingredients) are rendered as comma-separated values.
    """
    if not entities:
        return f"*No {entity_plural} extracted.*\n"

    lines: list[str] = []
    for e in entities:
        name = str(e.get("name", "")).strip()
        if not name:
            continue
        lines.append(f"### {name}")
        for k, v in e.items():
            if k == "name" or not v:
                continue
            label = k.replace("_", " ").title()
            if isinstance(v, list):
                rendered = ", ".join(str(x) for x in v if x)
                if rendered:
                    lines.append(f"- **{label}:** {rendered}")
            else:
                lines.append(f"- **{label}:** {v}")
        lines.append("")
    return "\n".join(lines)


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

def _heading_level_from_style_name(style_name: str) -> int | None:
    """Return 1–6 from a python-docx style name like 'Heading 3', or None."""
    m = re.match(r"^heading\s+(\d+)$", style_name.strip(), re.I)
    return int(m.group(1)) if m else None


def _docx_sections_at_level(doc, base: str, split_level: int) -> list[tuple[str, int]]:
    """
    Split doc into sections using headings at split_level as boundaries.
    Other heading levels (containers or sub-headings) are skipped so they
    don't inflate section entry counts.  Uses the python-docx paragraph API
    which resolves style names reliably without XML namespace juggling.
    """
    sections: list[tuple[str, int]] = []
    current_heading: str | None = None
    current_count = 0

    def flush():
        nonlocal current_heading, current_count
        if current_heading is not None:
            sections.append((current_heading, current_count))
        current_heading = None
        current_count = 0

    for para in doc.paragraphs:
        style_name = para.style.name if para.style else ""
        text = para.text.strip()
        lvl = _heading_level_from_style_name(style_name)
        if lvl == split_level:
            flush()
            current_heading = text or base
        elif lvl is not None:
            pass  # other heading level — structural container or sub-heading
        elif text:
            current_count += 1

    flush()
    return sections


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

    # Try heading levels H1 → H2 → H3, stopping at the first that yields ≥ 3 sections.
    # This handles docs where H1 is just a document title and real content lives under H2/H3.
    sections: list[tuple[str, int]] = []
    heading_level_used: int | None = None
    for level in (1, 2, 3):
        candidate = _docx_sections_at_level(doc, base, level)
        if len(candidate) >= 3:
            sections = candidate
            heading_level_used = level
            break

    if not sections:
        # No heading level produced ≥ 3 sections — use whole file as single register.
        total_rows = sum(max(0, len(t.rows) - 1) for t in doc.tables)
        para_count = len([p for p in doc.paragraphs if p.text.strip()])
        sections = [(base, total_rows or para_count)]
        file_notes = "No heading sections — treated as single register"
    else:
        label = f"Heading {heading_level_used}"
        file_notes = f"{len(sections)} {label} section{'s' if len(sections) != 1 else ''}"

    section_label = f"H{heading_level_used}" if heading_level_used else "section"
    registers = [
        ProposedRegister(
            slug=slugify(name),
            display_name=name,
            entry_count=count,
            source_file=filename,
            confidence=_confidence_doc(count),
            notes=f"{section_label} · {count} content rows" if count else f"{section_label} · no rows detected",
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


# ── Vocabulary alignment helpers ───────────────────────────────────────────────

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "recipes":     ["recipe", "menu", "meal", "dish", "breakfast", "lunch", "dinner",
                    "sauce", "cook", "food", "prep"],
    "ingredients": ["ingredient", "pantry", "stock", "inventory"],
    "partners":    ["purveyor", "vendor", "supplier", "partner", "fundrais", "outreach",
                    "grant", "sponsor", "donation", "confirmed"],
    "people":      ["people", "person", "staff", "volunteer", "crew", "team", "member",
                    "contact", "worker", "role"],
    "meeting_notes": ["meeting", "minutes", "notes", "agenda", "action", "carried"],
    "tasks":       ["task", "checklist", "todo", "shift", "schedule"],
}


def classify_register_category(slug: str, display_name: str, columns: list[str]) -> str:
    """Return a broad category slug for vocabulary alignment."""
    text = (slug + " " + display_name + " " + " ".join(columns)).lower()
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return cat
    return "records"


def _extract_declared_types(expectations_text: str) -> list[str]:
    """Parse one entity-type name per line from client vocabulary text."""
    types: list[str] = []
    for line in expectations_text.splitlines():
        line = line.strip()
        if not line:
            continue
        name = re.split(r"[:\-–,]", line)[0].strip().lower()
        if name and len(name) < 40:
            types.append(name)
    return types


# Common synonym expansions: if a client declares word X, also match these.
# The client's word is always the displayed label — these are search aids only.
_VOCAB_SYNONYMS: dict[str, list[str]] = {
    "recipe":      ["menu", "meal", "dish", "food", "cook", "prep"],
    "meal":        ["recipe", "menu", "dish", "food", "breakfast", "lunch", "dinner"],
    "menu":        ["recipe", "meal", "dish", "food"],
    "ingredient":  ["pantry", "stock", "inventory", "supply"],
    "purveyor":    ["vendor", "supplier", "partner", "fundrais", "outreach", "sponsor", "donation", "confirmed"],
    "vendor":      ["supplier", "purveyor", "partner", "outreach"],
    "supplier":    ["vendor", "purveyor", "partner"],
    "partner":     ["purveyor", "vendor", "supplier", "sponsor", "donor", "confirmed"],
    "staff":       ["crew", "team", "volunteer", "worker", "people", "person", "member", "contact", "role"],
    "people":      ["staff", "crew", "team", "volunteer", "member", "worker", "contact", "person", "role"],
    "person":      ["staff", "people", "crew", "team", "member", "worker"],
    "volunteer":   ["staff", "people", "crew", "member"],
    "task":        ["checklist", "todo", "action", "shift", "schedule", "prep"],
    "schedule":    ["task", "shift", "roster", "timetable"],
    "note":        ["meeting", "minutes", "memo", "agenda", "summary"],
    "meeting":     ["note", "minutes", "agenda", "action", "carried"],
}


def _word_variants(word: str) -> list[str]:
    """Return word + common inflected forms for substring matching."""
    word = word.lower().strip()
    variants = {word}
    # singular from plural: recipes→recipe, ingredients→ingredient
    if word.endswith("ies") and len(word) > 4:
        variants.add(word[:-3] + "y")
    if word.endswith("es") and len(word) > 4:
        variants.add(word[:-2])
    if word.endswith("s") and len(word) > 4 and not word.endswith("ss"):
        variants.add(word[:-1])
    return list(variants)


def _declared_matches_register(declared: str, reg: dict) -> bool:
    """Return True if this register plausibly contains the declared entity type."""
    text = " ".join([
        reg.get("slug", ""),
        reg.get("display_name", ""),
        reg.get("source_file", ""),   # file name is a strong signal ("Menu Meeting.docx" → menu)
        " ".join(reg.get("columns", [])),
    ]).lower()

    candidates = _word_variants(declared)
    # Direct substring match
    for c in candidates:
        if c in text:
            return True
    # Synonym match
    for c in candidates:
        for syn in _VOCAB_SYNONYMS.get(c, []):
            if syn in text:
                return True
    return False


def _infer_child_suggestions(aligned: list[dict], declared_set: set[str]) -> list[dict]:
    """
    Look at column names in aligned registers and flag columns that look like
    potential child entity types not already in declared_set.
    Returns a list of {parent: str, child_candidate: str, source_register: str}.
    """
    suggestions = []
    seen: set[str] = set()
    for reg in aligned:
        for col in reg.get("columns", []):
            col_lower = col.strip().lower()
            # Skip trivial/filter columns
            if len(col_lower) < 4 or col_lower in {"name", "date", "type", "id", "note", "notes", "status", "total", "count"}:
                continue
            # Already declared — not a suggestion
            if any(col_lower in _word_variants(d) or d in _word_variants(col_lower) for d in declared_set):
                continue
            key = (reg.get("matched_declared", ""), col_lower)
            if key not in seen:
                seen.add(key)
                suggestions.append({
                    "parent": reg.get("matched_declared", reg.get("display_name", "")),
                    "child_candidate": col,
                    "source_register": reg.get("display_name", ""),
                })
    return suggestions


def align_vocabulary(
    entity_expectations: str,
    found_registers: list[dict],
    general_context: str = "",
) -> dict:
    """
    Match found registers against the client's declared types directly.
    The declared types (from their intake form) ARE the target list —
    category keywords are a fallback only when no declarations exist.

    Returns {aligned, unexpected, absent, nested_in_parent, declared_types, child_suggestions}.

    nested_in_parent: declared types that are known shape-children of an aligned type —
    they are embedded inside those files and will surface in Phase 2 extraction,
    not absent from the dataset.
    """
    declared_types = _extract_declared_types(entity_expectations)

    if not declared_types:
        # No vocabulary declared — treat all registers as aligned, no absent
        return {
            "aligned": [dict(reg, matched_declared="") for reg in found_registers],
            "unexpected": [],
            "absent": [],
            "nested_in_parent": [],
            "declared_types": [],
            "child_suggestions": [],
        }

    declared_set = set(declared_types)
    aligned: list[dict] = []
    unexpected: list[dict] = []
    matched_declared_keys: set[str] = set()

    for reg in found_registers:
        matched = None
        for decl in declared_types:
            if _declared_matches_register(decl, reg):
                matched = decl
                matched_declared_keys.add(decl.lower())
                break
        if matched:
            aligned.append({**reg, "matched_declared": matched})
        else:
            unexpected.append(reg)

    raw_absent = [d for d in declared_types if d.lower() not in matched_declared_keys]
    child_suggestions = _infer_child_suggestions(aligned, declared_set)

    # Reclassify absent types that are shape-children of aligned types.
    # These aren't absent — they're nested inside the aligned files and will
    # surface as extracted entities in Phase 2, not as top-level registers.
    vertical = _detect_vertical(general_context) if general_context else None
    shape_children = VERTICAL_SHAPE_CHILDREN.get(vertical, {}) if vertical else {}
    child_to_parent: dict[str, str] = {
        child.lower(): parent.lower()
        for parent, children in shape_children.items()
        for child in children
    }
    aligned_declared_lowered = {r.get("matched_declared", "").lower() for r in aligned}
    # Expand to singular/plural variants so "recipes" matches parent key "recipe", etc.
    aligned_declared_variants: set[str] = set()
    for ad in aligned_declared_lowered:
        aligned_declared_variants.update(_word_variants(ad))

    absent: list[str] = []
    nested_in_parent: list[dict] = []
    for d in raw_absent:
        parent = child_to_parent.get(d.lower())
        if parent and parent in aligned_declared_variants:
            nested_in_parent.append({"type": d, "nested_in": parent})
        else:
            # Check word variants of d against the child map
            matched_as_child = False
            for variant in _word_variants(d):
                parent = child_to_parent.get(variant)
                if parent and parent in aligned_declared_variants:
                    nested_in_parent.append({"type": d, "nested_in": parent})
                    matched_as_child = True
                    break
            if not matched_as_child:
                absent.append(d)

    return {
        "aligned": aligned,
        "unexpected": unexpected,
        "absent": absent,
        "nested_in_parent": nested_in_parent,
        "declared_types": declared_types,
        "child_suggestions": child_suggestions,
    }
