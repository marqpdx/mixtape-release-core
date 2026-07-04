from __future__ import annotations

from html import escape
import re
from urllib.parse import quote

from django.http import HttpResponse
from django.utils.text import slugify

from writing.models import WorkingDocument, WritingPiece

PDF_EXPORT_STYLES = """
@page {
  size: A4;
  margin: 18mm 16mm 18mm 16mm;
}
body {
  color: #111827;
  font-family: Georgia, "Times New Roman", serif;
  font-size: 11pt;
  line-height: 1.55;
}
header {
  border-bottom: 1px solid #d1d5db;
  margin-bottom: 20px;
  padding-bottom: 12px;
}
h1 {
  font-size: 24pt;
  line-height: 1.2;
  margin: 0 0 6px 0;
}
h2, h3, h4, h5, h6 {
  line-height: 1.25;
  margin: 18px 0 8px;
  page-break-after: avoid;
}
p.excerpt {
  color: #4b5563;
  font-size: 10.5pt;
  margin: 6px 0 0 0;
}
p, ul, ol, blockquote, pre, table {
  margin: 0 0 12px 0;
}
ul, ol {
  padding-left: 24px;
}
blockquote {
  border-left: 3px solid #d1d5db;
  color: #374151;
  margin-left: 0;
  padding-left: 12px;
}
pre {
  background: #f3f4f6;
  border-radius: 6px;
  overflow-wrap: anywhere;
  padding: 12px;
  white-space: pre-wrap;
}
code {
  background: #f3f4f6;
  border-radius: 3px;
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 0.92em;
  padding: 0.08em 0.25em;
}
pre code {
  background: transparent;
  padding: 0;
}
hr {
  border: 0;
  border-top: 1px solid #d1d5db;
  margin: 18px 0;
}
img {
  height: auto;
  max-width: 100%;
}
table {
  border-collapse: collapse;
  width: 100%;
}
th, td {
  border: 1px solid #d1d5db;
  padding: 6px 8px;
  text-align: left;
  vertical-align: top;
}
.muted {
  color: #6b7280;
  font-size: 9pt;
}
"""


def _find_accessible_working_document(piece: WritingPiece, user) -> WorkingDocument | None:
    working_doc = WorkingDocument.objects.select_related("dispatch_content").filter(piece=piece, user=user).first()
    if working_doc:
        return working_doc
    return WorkingDocument.objects.select_related("dispatch_content").filter(piece=piece, user=piece.author).first()


def get_pdf_export_source_for_user(piece: WritingPiece, user) -> dict:
    working_doc = _find_accessible_working_document(piece, user)

    if working_doc and working_doc.dispatch_content:
        dispatch_content = working_doc.dispatch_content
        body_json = working_doc.body_json or dispatch_content.content_snapshot or piece.body_json or {}
        return {
            "title": working_doc.title or piece.title or "Untitled",
            "excerpt": working_doc.excerpt or piece.excerpt or "",
            "body_json": body_json,
            "source_kind": "dispatch_content",
            "working_document_id": str(working_doc.id),
            "dispatch_content_id": str(dispatch_content.id),
        }

    if working_doc:
        return {
            "title": working_doc.title or piece.title or "Untitled",
            "excerpt": working_doc.excerpt or piece.excerpt or "",
            "body_json": working_doc.body_json or piece.body_json or {},
            "source_kind": "working_document",
            "working_document_id": str(working_doc.id),
            "dispatch_content_id": None,
        }

    return {
        "title": piece.title or "Untitled",
        "excerpt": piece.excerpt or "",
        "body_json": piece.body_json or {},
        "source_kind": "writing_piece",
        "working_document_id": None,
        "dispatch_content_id": None,
    }


def _extract_text(node: dict | None) -> str:
    if not node:
        return ""
    if node.get("type") == "text":
        return node.get("text", "") or ""
    return "".join(_extract_text(child) for child in (node.get("content") or []))


def _render_marks(text: str, marks: list[dict] | None) -> str:
    rendered = escape(text)
    for mark in marks or []:
        mark_type = mark.get("type")
        attrs = mark.get("attrs") or {}
        if mark_type == "bold":
            rendered = f"<strong>{rendered}</strong>"
        elif mark_type == "italic":
            rendered = f"<em>{rendered}</em>"
        elif mark_type == "strike":
            rendered = f"<s>{rendered}</s>"
        elif mark_type == "code":
            rendered = f"<code>{rendered}</code>"
        elif mark_type == "link":
            href = escape(attrs.get("href") or "#", quote=True)
            rendered = f'<a href="{href}">{rendered}</a>'
    return rendered


def _render_inline(node: dict | None) -> str:
    if not node:
        return ""
    node_type = node.get("type")
    if node_type == "text":
        return _render_marks(node.get("text", "") or "", node.get("marks"))
    if node_type == "hardBreak":
        return "<br />"
    return "".join(_render_inline(child) for child in (node.get("content") or []))


def _render_children(node: dict | None) -> str:
    return "".join(_render_block(child) for child in (node or {}).get("content") or [])


def _render_list_items(items: list[dict], tag: str) -> str:
    parts = []
    for item in items:
        inner = []
        for child in item.get("content") or []:
            if child.get("type") == "paragraph":
                inner.append(_render_inline(child))
            else:
                inner.append(_render_block(child))
        parts.append(f"<li>{''.join(inner) or '&nbsp;'}</li>")
    return f"<{tag}>{''.join(parts)}</{tag}>"


def _render_table(node: dict) -> str:
    rows = []
    for row in node.get("content") or []:
        cells = []
        for cell in row.get("content") or []:
            cell_tag = "th" if cell.get("type") == "tableHeader" else "td"
            cell_inner = "".join(_render_block(child) for child in (cell.get("content") or [])) or "&nbsp;"
            cells.append(f"<{cell_tag}>{cell_inner}</{cell_tag}>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return f"<table><tbody>{''.join(rows)}</tbody></table>"


def _render_block(node: dict | None) -> str:
    if not node:
        return ""
    node_type = node.get("type")
    attrs = node.get("attrs") or {}

    if node_type == "paragraph":
        inner = _render_inline(node)
        return f"<p>{inner or '&nbsp;'}</p>"
    if node_type == "heading":
        level = max(1, min(int(attrs.get("level") or 1), 6))
        return f"<h{level}>{_render_inline(node) or '&nbsp;'}</h{level}>"
    if node_type == "bulletList":
        return _render_list_items(node.get("content") or [], "ul")
    if node_type == "orderedList":
        start = attrs.get("start")
        start_attr = f' start="{int(start)}"' if start else ""
        items_html = _render_list_items(node.get("content") or [], "ol")
        return items_html.replace("<ol>", f"<ol{start_attr}>", 1)
    if node_type == "blockquote":
        return f"<blockquote>{_render_children(node)}</blockquote>"
    if node_type == "codeBlock":
        return f"<pre><code>{escape(_extract_text(node))}</code></pre>"
    if node_type == "horizontalRule":
        return "<hr />"
    if node_type == "image":
        src = escape(attrs.get("src") or "", quote=True)
        alt = escape(attrs.get("alt") or "")
        return f'<figure><img src="{src}" alt="{alt}" /></figure>' if src else ""
    if node_type == "table":
        return _render_table(node)
    if node_type == "outlineMarker":
        return ""
    return f"<p>{_render_inline(node) or escape(_extract_text(node)) or '&nbsp;'}</p>"


def render_printable_html(*, title: str, excerpt: str, body_json: dict, author_name: str | None = None, sponsor_name: str | None = None) -> str:
    body = "".join(_render_block(node) for node in (body_json or {}).get("content") or [])
    meta_bits = [bit for bit in [author_name, sponsor_name] if bit]
    meta_html = f'<p class="muted">{" • ".join(escape(bit) for bit in meta_bits)}</p>' if meta_bits else ""
    excerpt_html = f'<p class="excerpt">{escape(excerpt)}</p>' if excerpt else ""
    return (
        '<!doctype html><html><head><meta charset="utf-8" /></head><body>'
        f"<header><h1>{escape(title or 'Untitled')}</h1>{meta_html}{excerpt_html}</header>"
        f"<main>{body}</main>"
        "</body></html>"
    )


def generate_pdf_bytes(*, html: str) -> bytes:
    try:
        from weasyprint import CSS, HTML
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("WeasyPrint is required for PDF export but is not installed or is missing native dependencies") from exc
    return HTML(string=html).write_pdf(stylesheets=[CSS(string=PDF_EXPORT_STYLES)])


def _build_filename(title: str) -> str:
    base = slugify(title or "untitled") or "untitled"
    return f"{re.sub(r'[^a-z0-9-]+', '-', base).strip('-') or 'untitled'}.pdf"


def build_pdf_export_response(*, piece: WritingPiece, title: str, excerpt: str, body_json: dict, source_kind: str) -> HttpResponse:
    sponsor = piece.sponsor
    sponsor_name = getattr(sponsor, "title", None) or getattr(sponsor, "name", None)
    html = render_printable_html(
        title=title,
        excerpt=excerpt,
        body_json=body_json,
        author_name=piece.author_name,
        sponsor_name=sponsor_name,
    )
    pdf_bytes = generate_pdf_bytes(html=html)
    filename = _build_filename(title)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}"
    response["X-Export-Source-Kind"] = source_kind
    return response
