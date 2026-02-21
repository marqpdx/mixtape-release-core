# writing/importers/docx_to_tiptap.py
"""
Convert .docx files to TipTap/ProseMirror JSON.

Pure functions with no Django dependencies — takes a file path or bytes,
returns a dict matching the TipTap document schema.
"""

import io
import re
import uuid
from pathlib import Path
from xml.etree import ElementTree

import docx
from docx.oxml.ns import qn


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def docx_to_tiptap(source: str | bytes | Path) -> dict:
    """
    Convert a .docx file to TipTap JSON.

    Args:
        source: file path (str/Path) or raw bytes of a .docx file.

    Returns:
        {"type": "doc", "content": [...]}
    """
    if isinstance(source, (str, Path)):
        doc = docx.Document(str(source))
    else:
        doc = docx.Document(io.BytesIO(source))

    content = []
    list_state = _ListState()

    for para in doc.paragraphs:
        style_name = para.style.name or ""

        # Check for heading
        heading_level = _heading_level(style_name)

        # Check for list membership
        num_info = _get_numbering_info(para)

        if num_info is not None:
            num_id, ilvl, is_ordered = num_info
            node = _paragraph_to_node(para, "paragraph")
            list_state.add_item(content, node, ilvl, is_ordered)
            continue

        # Not a list — flush any open lists
        list_state.flush(content)

        if heading_level is not None:
            node = _paragraph_to_node(para, "heading", level=heading_level)
            if node:
                content.append(node)
        elif _is_blockquote_style(style_name):
            node = _paragraph_to_node(para, "paragraph")
            if node:
                content.append({
                    "type": "blockquote",
                    "attrs": {"data-block-id": str(uuid.uuid4())},
                    "content": [node],
                })
        elif _is_horizontal_rule(para):
            content.append({"type": "horizontalRule"})
        else:
            node = _paragraph_to_node(para, "paragraph")
            if node:
                content.append(node)

    # Flush remaining lists
    list_state.flush(content)

    # Ensure at least one node
    if not content:
        content.append({
            "type": "paragraph",
            "attrs": {"data-block-id": str(uuid.uuid4())},
        })

    return {"type": "doc", "content": content}


def generate_outline_from_headings(tiptap_json: dict) -> list[dict]:
    """
    Extract headings from TipTap JSON and insert outlineMarker nodes.

    Mutates tiptap_json in place (inserts marker nodes after headings).

    Returns:
        List of outline node specs:
        [{"title": str, "order_index": int, "anchor_target": str, "level": int}, ...]
    """
    outline_specs = []
    content = tiptap_json.get("content", [])
    order = 0

    # Walk content in reverse so insertions don't shift indices
    insert_ops = []

    for i, node in enumerate(content):
        if node.get("type") == "heading":
            level = node.get("attrs", {}).get("level", 1)
            title = _extract_text(node)
            if not title.strip():
                continue

            marker_id = str(uuid.uuid4())
            marker_node = {
                "type": "outlineMarker",
                "attrs": {"nodeId": marker_id},
            }
            insert_ops.append((i + 1, marker_node))

            outline_specs.append({
                "title": title.strip(),
                "order_index": order,
                "anchor_target": marker_id,
                "level": level,
            })
            order += 1

    # Insert markers (reverse order to preserve indices)
    for idx, marker in reversed(insert_ops):
        content.insert(idx, marker)

    return outline_specs


def extract_title(tiptap_json: dict) -> str | None:
    """Extract title from the first heading in the document."""
    for node in tiptap_json.get("content", []):
        if node.get("type") == "heading":
            text = _extract_text(node)
            if text.strip():
                return text.strip()
    return None


def count_nodes_by_type(tiptap_json: dict) -> dict[str, int]:
    """Count nodes by type for import stats."""
    counts: dict[str, int] = {}

    def walk(node: dict):
        node_type = node.get("type", "unknown")
        counts[node_type] = counts.get(node_type, 0) + 1
        for child in node.get("content", []):
            walk(child)

    walk(tiptap_json)
    return counts


# ---------------------------------------------------------------------------
# Internals — heading/style detection
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^Heading\s+(\d)$", re.IGNORECASE)


def _heading_level(style_name: str) -> int | None:
    m = _HEADING_RE.match(style_name)
    if m:
        level = int(m.group(1))
        return min(level, 6)
    # Also handle Title style as H1
    if style_name.lower() in ("title",):
        return 1
    if style_name.lower() in ("subtitle",):
        return 2
    return None


def _is_blockquote_style(style_name: str) -> bool:
    lower = style_name.lower()
    return lower in ("quote", "block text", "block quote", "intense quote")


def _is_horizontal_rule(para) -> bool:
    """Detect a paragraph that's just a horizontal rule."""
    # Word horizontal rules are often pPr/pBdr with a bottom border only
    # and no text content
    if para.text.strip():
        return False
    pPr = para._element.find(qn("w:pPr"))
    if pPr is not None:
        pBdr = pPr.find(qn("w:pBdr"))
        if pBdr is not None:
            return True
    return False


# ---------------------------------------------------------------------------
# Internals — list handling
# ---------------------------------------------------------------------------

def _get_numbering_info(para) -> tuple[str, int, bool] | None:
    """
    Extract numbering info from a paragraph.
    Returns (numId, ilvl, is_ordered) or None if not a list item.
    """
    pPr = para._element.find(qn("w:pPr"))
    if pPr is None:
        return None

    numPr = pPr.find(qn("w:numPr"))
    if numPr is None:
        # Check style-based list (e.g. "List Bullet", "List Number")
        style_name = (para.style.name or "").lower()
        if any(kw in style_name for kw in ("list bullet", "list paragraph")):
            return ("style-bullet", 0, False)
        if any(kw in style_name for kw in ("list number", "list continue")):
            return ("style-number", 0, True)
        return None

    ilvl_el = numPr.find(qn("w:ilvl"))
    numId_el = numPr.find(qn("w:numId"))

    if numId_el is None:
        return None

    num_id = numId_el.get(qn("w:val"), "0")
    ilvl = int(ilvl_el.get(qn("w:val"), "0")) if ilvl_el is not None else 0

    # Determine if ordered — heuristic based on style name
    style_name = (para.style.name or "").lower()
    is_ordered = "number" in style_name or "ordered" in style_name

    # Also check the abstract numbering format if available
    if not is_ordered:
        try:
            numbering_part = para.part.numbering_part
            if numbering_part is not None:
                num_el = numbering_part.element
                # Look for the numFmt
                for abstract_num in num_el.findall(qn("w:abstractNum")):
                    for lvl in abstract_num.findall(qn("w:lvl")):
                        lvl_ilvl = lvl.get(qn("w:ilvl"), "0")
                        if lvl_ilvl == str(ilvl):
                            num_fmt = lvl.find(qn("w:numFmt"))
                            if num_fmt is not None:
                                fmt_val = num_fmt.get(qn("w:val"), "")
                                if fmt_val in ("decimal", "upperRoman", "lowerRoman",
                                               "upperLetter", "lowerLetter"):
                                    is_ordered = True
                            break
        except Exception:
            pass

    return (num_id, ilvl, is_ordered)


class _ListState:
    """Tracks open list nesting to build TipTap list structures."""

    def __init__(self):
        self._stack: list[dict] = []  # stack of list nodes
        self._depths: list[int] = []  # corresponding ilvl for each

    def add_item(self, content: list, para_node: dict, ilvl: int, is_ordered: bool):
        list_type = "orderedList" if is_ordered else "bulletList"

        list_item = {
            "type": "listItem",
            "attrs": {"data-block-id": str(uuid.uuid4())},
            "content": [para_node] if para_node else [{
                "type": "paragraph",
                "attrs": {"data-block-id": str(uuid.uuid4())},
            }],
        }

        if not self._stack:
            # Start a new top-level list
            new_list = {
                "type": list_type,
                "attrs": {"data-block-id": str(uuid.uuid4())},
                "content": [list_item],
            }
            self._stack.append(new_list)
            self._depths.append(ilvl)
            return

        # If list type changed at the same level, flush and start new list
        if self._depths[-1] == ilvl and self._stack[-1]["type"] != list_type:
            self.flush(content)
            new_list = {
                "type": list_type,
                "attrs": {"data-block-id": str(uuid.uuid4())},
                "content": [list_item],
            }
            self._stack.append(new_list)
            self._depths.append(ilvl)
            return

        # Same or shallower level — pop back
        while len(self._depths) > 1 and self._depths[-1] > ilvl:
            self._stack.pop()
            self._depths.pop()

        if self._depths[-1] == ilvl:
            # Same level — add to current list
            self._stack[-1]["content"].append(list_item)
        elif ilvl > self._depths[-1]:
            # Deeper — nest inside the last list item
            parent_list = self._stack[-1]
            last_item = parent_list["content"][-1]

            nested_list = {
                "type": list_type,
                "attrs": {"data-block-id": str(uuid.uuid4())},
                "content": [list_item],
            }
            last_item["content"].append(nested_list)

            self._stack.append(nested_list)
            self._depths.append(ilvl)
        else:
            # Shallower than anything on stack — add to current top
            self._stack[-1]["content"].append(list_item)

    def flush(self, content: list):
        if self._stack:
            content.append(self._stack[0])  # append root list
            self._stack.clear()
            self._depths.clear()


# ---------------------------------------------------------------------------
# Internals — run/text extraction
# ---------------------------------------------------------------------------

def _paragraph_to_node(para, node_type: str, level: int | None = None) -> dict | None:
    """Convert a docx paragraph to a TipTap node."""
    runs = _extract_runs(para)

    attrs: dict = {"data-block-id": str(uuid.uuid4())}
    if node_type == "heading" and level is not None:
        attrs["level"] = level

    node: dict = {"type": node_type, "attrs": attrs}

    if runs:
        node["content"] = runs

    return node


def _extract_runs(para) -> list[dict]:
    """Extract text runs with marks from a paragraph."""
    nodes = []

    for child in para._element:
        tag = child.tag

        if tag == qn("w:r"):
            # Regular run
            text = ""
            marks = []
            has_break = False

            rPr = child.find(qn("w:rPr"))
            if rPr is not None:
                if rPr.find(qn("w:b")) is not None:
                    marks.append({"type": "bold"})
                if rPr.find(qn("w:i")) is not None:
                    marks.append({"type": "italic"})
                if rPr.find(qn("w:u")) is not None:
                    u_val = rPr.find(qn("w:u")).get(qn("w:val"), "single")
                    if u_val != "none":
                        marks.append({"type": "underline"})
                if rPr.find(qn("w:rStyle")) is not None:
                    style_val = rPr.find(qn("w:rStyle")).get(qn("w:val"), "")
                    if style_val.lower() in ("code", "verbatimchar", "inlinecode"):
                        marks.append({"type": "code"})

            for el in child:
                if el.tag == qn("w:t"):
                    text += el.text or ""
                elif el.tag == qn("w:br"):
                    has_break = True

            if text:
                text_node: dict = {"type": "text", "text": text}
                if marks:
                    text_node["marks"] = marks
                nodes.append(text_node)

            if has_break:
                nodes.append({"type": "hardBreak"})

        elif tag == qn("w:hyperlink"):
            # Hyperlink
            href = _extract_hyperlink_url(para, child)
            link_text = ""
            link_marks: list[dict] = []

            for r in child.findall(qn("w:r")):
                for t in r.findall(qn("w:t")):
                    link_text += t.text or ""

                rPr = r.find(qn("w:rPr"))
                if rPr is not None:
                    if rPr.find(qn("w:b")) is not None and not any(m["type"] == "bold" for m in link_marks):
                        link_marks.append({"type": "bold"})
                    if rPr.find(qn("w:i")) is not None and not any(m["type"] == "italic" for m in link_marks):
                        link_marks.append({"type": "italic"})

            if link_text:
                marks = [{"type": "link", "attrs": {"href": href or ""}}]
                marks.extend(link_marks)
                nodes.append({"type": "text", "text": link_text, "marks": marks})

    return nodes


def _extract_hyperlink_url(para, hyperlink_el) -> str | None:
    """Extract URL from a hyperlink element."""
    # Check for r:id (relationship-based hyperlink)
    r_id = hyperlink_el.get(qn("r:id"))
    if r_id:
        try:
            rel = para.part.rels[r_id]
            return rel.target_ref
        except (KeyError, AttributeError):
            pass

    # Check for w:anchor (internal bookmark)
    anchor = hyperlink_el.get(qn("w:anchor"))
    if anchor:
        return f"#{anchor}"

    return None


def _extract_text(node: dict) -> str:
    """Extract plain text from a TipTap node recursively."""
    if node.get("type") == "text":
        return node.get("text", "")
    parts = []
    for child in node.get("content", []):
        parts.append(_extract_text(child))
    return "".join(parts)
