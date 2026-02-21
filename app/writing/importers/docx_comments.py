# writing/importers/docx_comments.py
"""
Extract comments from .docx files.

Comments live in word/comments.xml inside the .docx ZIP.
Google Docs exports may or may not include them.
"""

import zipfile
from pathlib import Path
from xml.etree import ElementTree


# WordprocessingML namespace
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def extract_docx_comments(source: str | Path) -> list[dict]:
    """
    Extract comments from a .docx file.

    Args:
        source: path to the .docx file.

    Returns:
        List of comment dicts:
        [{"id": str, "author": str, "date": str, "text": str}, ...]
    """
    source = str(source)
    comments = []

    try:
        with zipfile.ZipFile(source, "r") as zf:
            if "word/comments.xml" not in zf.namelist():
                return []

            with zf.open("word/comments.xml") as f:
                tree = ElementTree.parse(f)
                root = tree.getroot()

                for comment_el in root.findall(f"{{{_W_NS}}}comment"):
                    comment_id = comment_el.get(f"{{{_W_NS}}}id", "")
                    author = comment_el.get(f"{{{_W_NS}}}author", "")
                    date = comment_el.get(f"{{{_W_NS}}}date", "")

                    # Extract text from all <w:p>/<w:r>/<w:t> elements
                    text_parts = []
                    for p in comment_el.findall(f".//{{{_W_NS}}}t"):
                        if p.text:
                            text_parts.append(p.text)

                    text = " ".join(text_parts).strip()

                    if text or author:
                        comments.append({
                            "id": comment_id,
                            "author": author,
                            "date": date,
                            "text": text,
                        })

    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError):
        return []

    return comments
