# apps/writing/utils.py
def first_line_as_title(text: str, limit: int = 140) -> str:
    return (text.splitlines()[0] if text else "").strip()[:limit]

def plaintext_to_tiptap_json(text: str) -> dict:
    """
    Minimal transform so WorkingCopy editor can open content immediately.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": p}]}
            for p in paragraphs
        ] or [{"type": "paragraph"}]
    }
