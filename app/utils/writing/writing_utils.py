# api/utils/writing_utils.py

import re
import uuid
from typing import Any

from django.utils.text import slugify


# Maximum attempts to find a unique slug
MAX_SLUG_ATTEMPTS = 1000


def generate_unique_slug(title: str, model_class, max_length: int = 50) -> str:
    """
    Generate a unique slug from title, handling duplicates.

    Args:
        title: The title to slugify
        model_class: The model class to check for existing slugs
        max_length: Maximum length of the slug

    Returns:
        A unique slug string
    """
    base_slug = slugify(title)[:max_length]

    if not base_slug:
        base_slug = f"post-{uuid.uuid4().hex[:8]}"

    slug = base_slug
    counter = 2

    while model_class.objects.filter(slug=slug).exists():
        if counter > MAX_SLUG_ATTEMPTS:
            raise ValueError(f"Too many duplicate slugs for base '{base_slug}'")

        suffix = f"-{counter}"
        max_base_length = max_length - len(suffix)
        slug = f"{base_slug[:max_base_length]}{suffix}"
        counter += 1

    return slug


def extract_text_from_prosemirror(doc: dict[Any, Any]) -> str:
    """
    Extract plain text from ProseMirror document structure.

    Args:
        doc: ProseMirror document JSON

    Returns:
        Plain text string
    """
    if not doc or not isinstance(doc, dict) or "content" not in doc:
        return ""

    def extract_from_node(node: dict[Any, Any]) -> str:
        if not isinstance(node, dict):
            return ""

        # Text nodes contain the actual text
        if node.get("type") == "text":
            return node.get("text", "")

        # Nodes with content have child nodes
        if "content" in node and isinstance(node["content"], list):
            return " ".join(extract_from_node(child) for child in node["content"])

        return ""

    try:
        text_parts = [extract_from_node(node) for node in doc["content"]]
        return " ".join(filter(None, text_parts))
    except (KeyError, TypeError):
        return ""


_HTML_ESCAPE = str.maketrans({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"})


def _escape(text: str) -> str:
    return text.translate(_HTML_ESCAPE)


def _apply_marks(text: str, marks: list) -> str:
    for mark in reversed(marks):
        kind = mark.get("type", "")
        if kind == "bold":
            text = f"<strong>{text}</strong>"
        elif kind == "italic":
            text = f"<em>{text}</em>"
        elif kind == "code":
            text = f"<code>{text}</code>"
        elif kind == "strike":
            text = f"<s>{text}</s>"
        elif kind == "underline":
            text = f"<u>{text}</u>"
        elif kind == "link":
            href = _escape(mark.get("attrs", {}).get("href", ""))
            text = f'<a href="{href}">{text}</a>'
    return text


def _render_node(node: dict) -> str:
    if not isinstance(node, dict):
        return ""
    kind = node.get("type", "")
    children = node.get("content", [])

    if kind == "text":
        text = _escape(node.get("text", ""))
        marks = node.get("marks", [])
        if marks:
            text = _apply_marks(text, marks)
        return text

    if kind == "doc":
        return "".join(_render_node(c) for c in children)

    if kind == "paragraph":
        inner = "".join(_render_node(c) for c in children)
        return f"<p>{inner}</p>"

    if kind == "heading":
        level = node.get("attrs", {}).get("level", 1)
        inner = "".join(_render_node(c) for c in children)
        return f"<h{level}>{inner}</h{level}>"

    if kind == "hardBreak":
        return "<br>"

    if kind == "bulletList":
        inner = "".join(_render_node(c) for c in children)
        return f"<ul>{inner}</ul>"

    if kind == "orderedList":
        inner = "".join(_render_node(c) for c in children)
        return f"<ol>{inner}</ol>"

    if kind == "listItem":
        inner = "".join(_render_node(c) for c in children)
        return f"<li>{inner}</li>"

    if kind == "blockquote":
        inner = "".join(_render_node(c) for c in children)
        return f"<blockquote>{inner}</blockquote>"

    if kind == "codeBlock":
        inner = "".join(_render_node(c) for c in children)
        return f"<pre><code>{inner}</code></pre>"

    if kind == "horizontalRule":
        return "<hr>"

    # Unknown node — render children if any
    return "".join(_render_node(c) for c in children)


def render_html_from_prosemirror(doc: dict) -> str:
    """
    Render a ProseMirror document to HTML at emit time. Never stored.
    Covers all standard Tiptap node types for prose content.
    """
    if not doc or not isinstance(doc, dict):
        return ""
    return _render_node(doc)


def estimate_reading_time(text: str, words_per_minute: int = 200) -> int:
    """
    Estimate reading time in minutes from text.

    Args:
        text: The text to analyze
        words_per_minute: Average reading speed

    Returns:
        Estimated reading time in minutes
    """
    if not text:
        return 0

    word_count = len(text.split())
    minutes = max(1, round(word_count / words_per_minute))
    return minutes


def count_words_in_prosemirror(doc: dict[Any, Any]) -> int:
    """
    Count words in a ProseMirror document.

    Args:
        doc: ProseMirror document JSON

    Returns:
        Word count
    """
    text = extract_text_from_prosemirror(doc)
    if not text:
        return 0
    return len(text.split())


def generate_excerpt(text: str, max_length: int = 200) -> str:
    """
    Generate an excerpt from text.

    Args:
        text: The full text
        max_length: Maximum length of excerpt

    Returns:
        Excerpt string
    """
    if not text:
        return ""

    if len(text) <= max_length:
        return text

    # Try to break at sentence boundary
    sentences = re.split(r"[.!?]+", text[:max_length + 50])
    if len(sentences) > 1:
        excerpt = sentences[0] + "."
        if len(excerpt) <= max_length:
            return excerpt

    # Fall back to word boundary
    words = text[:max_length].split()
    if words:
        excerpt = " ".join(words[:-1]) + "..."
        return excerpt

    return text[:max_length] + "..."


def validate_writing_kind(writing_kind: str) -> bool:
    """
    Validate that writing_kind is one of the allowed choices.

    Args:
        writing_kind: The writing kind to validate

    Returns:
        True if valid, False otherwise
    """
    allowed_kinds = [
        "post", "article", "dispatch", "forum",
        "announcement", "almanac", "page", "other"
    ]
    return writing_kind in allowed_kinds


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename for safe storage.

    Args:
        filename: The filename to sanitize

    Returns:
        Sanitized filename
    """
    # Remove or replace unsafe characters
    filename = re.sub(r"[^\w\s.-]", "", filename)
    filename = re.sub(r"[-\s]+", "-", filename)
    return filename.strip("-")
