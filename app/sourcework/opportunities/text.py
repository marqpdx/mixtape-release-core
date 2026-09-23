from __future__ import annotations

from html.parser import HTMLParser
import re


EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


class _ReadableHTMLParser(HTMLParser):
    BLOCK_TAGS = {
        "address",
        "article",
        "blockquote",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "section",
        "table",
        "tr",
    }
    IGNORED_TAGS = {"script", "style", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs):
        tag = tag.lower()
        if tag in self.IGNORED_TAGS:
            self.ignored_depth += 1
            return
        if self.ignored_depth:
            return
        if tag in self.BLOCK_TAGS or tag == "br":
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n- ")

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if tag in self.IGNORED_TAGS:
            self.ignored_depth = max(0, self.ignored_depth - 1)
            return
        if not self.ignored_depth and (tag in self.BLOCK_TAGS or tag == "li"):
            self.parts.append("\n")

    def handle_data(self, data: str):
        if not self.ignored_depth:
            self.parts.append(data)


def html_to_readable_text(value: str) -> str:
    """Convert untrusted listing HTML into readable plain text without rendering it."""

    if not value:
        return ""
    parser = _ReadableHTMLParser()
    parser.feed(value)
    parser.close()
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(^- [^\n]+)\n\n(?=- )", r"\1\n", text, flags=re.MULTILINE)
    return text.strip()


def extract_email_addresses(value: str) -> list[str]:
    return list(dict.fromkeys(match.group(0) for match in EMAIL_PATTERN.finditer(value or "")))
