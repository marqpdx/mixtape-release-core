"""
Body adapters for converting TipTap JSON segments to/from artifact-specific
body formats during checkpoint extraction and session initialization.

Each adapter handles one artifact type's body field.
"""

from writing.utils import plaintext_to_tiptap_json


def tiptap_json_to_plaintext(fragment: dict | list) -> str:
    """
    Extract plain text from a TipTap JSON fragment.
    Handles both a full doc node and a list of content nodes.
    """
    if isinstance(fragment, dict):
        nodes = fragment.get("content", [])
    elif isinstance(fragment, list):
        nodes = fragment
    else:
        return ""

    lines = []
    for node in nodes:
        node_type = node.get("type", "")
        if node_type in ("paragraph", "heading"):
            text_parts = []
            for child in node.get("content", []):
                if child.get("type") == "text":
                    text_parts.append(child.get("text", ""))
            lines.append("".join(text_parts))
        elif node_type == "bulletList" or node_type == "orderedList":
            for item in node.get("content", []):
                # Each listItem contains paragraphs
                item_text = tiptap_json_to_plaintext(item)
                if item_text:
                    lines.append(f"- {item_text}")
        elif node_type == "listItem":
            return tiptap_json_to_plaintext(node)
        elif node_type == "blockquote":
            inner = tiptap_json_to_plaintext(node)
            if inner:
                lines.append(inner)
        elif node_type == "hardBreak":
            lines.append("")

    return "\n\n".join(line for line in lines if line)


class WritingPieceAdapter:
    """WritingPiece stores TipTap JSON directly — passthrough."""

    @staticmethod
    def extract_body(tiptap_fragment: dict | list) -> dict:
        if isinstance(tiptap_fragment, list):
            return {"type": "doc", "content": tiptap_fragment}
        return tiptap_fragment

    @staticmethod
    def inject_body(stored_body) -> dict:
        if isinstance(stored_body, dict):
            return stored_body
        return {"type": "doc", "content": []}

    @staticmethod
    def apply_to_artifact(artifact, extracted_body):
        """Update the artifact's body_json field."""
        artifact.body_json = extracted_body
        artifact.save(update_fields=["body_json", "updated_at"])


class EventAdapter:
    """Event stores description as plain text."""

    @staticmethod
    def extract_body(tiptap_fragment: dict | list) -> str:
        return tiptap_json_to_plaintext(tiptap_fragment)

    @staticmethod
    def inject_body(stored_body) -> dict:
        if not stored_body:
            return {"type": "doc", "content": [{"type": "paragraph"}]}
        return plaintext_to_tiptap_json(stored_body)

    @staticmethod
    def apply_to_artifact(artifact, extracted_body):
        """Update the artifact's description field."""
        artifact.description = extracted_body
        artifact.save(update_fields=["description", "updated_at"])


class CourseAdapter:
    """Course inherits body from BaseContent — plain text."""

    @staticmethod
    def extract_body(tiptap_fragment: dict | list) -> str:
        return tiptap_json_to_plaintext(tiptap_fragment)

    @staticmethod
    def inject_body(stored_body) -> dict:
        if not stored_body:
            return {"type": "doc", "content": [{"type": "paragraph"}]}
        return plaintext_to_tiptap_json(stored_body)

    @staticmethod
    def apply_to_artifact(artifact, extracted_body):
        """Update the artifact's body field (from BaseContent)."""
        artifact.body = extracted_body
        artifact.save(update_fields=["body", "updated_at"])


class SeedAdapter:
    """Seed stores body_text as plain text."""

    @staticmethod
    def extract_body(tiptap_fragment: dict | list) -> str:
        return tiptap_json_to_plaintext(tiptap_fragment)

    @staticmethod
    def inject_body(stored_body) -> dict:
        if not stored_body:
            return {"type": "doc", "content": [{"type": "paragraph"}]}
        return plaintext_to_tiptap_json(stored_body)

    @staticmethod
    def apply_to_artifact(artifact, extracted_body):
        """Update the artifact's body_text field."""
        artifact.body_text = extracted_body
        artifact.save(update_fields=["body_text", "updated_at"])


# Registry keyed by artifact type string (lowercase model name)
ADAPTERS = {
    "writingpiece": WritingPieceAdapter,
    "event": EventAdapter,
    "course": CourseAdapter,
    "seed": SeedAdapter,
}


def get_adapter(artifact_type: str):
    """
    Look up the body adapter for an artifact type string.
    Type string is case-insensitive.
    """
    key = artifact_type.lower()
    adapter = ADAPTERS.get(key)
    if adapter is None:
        raise ValueError(f"No body adapter registered for artifact type: {artifact_type}")
    return adapter
