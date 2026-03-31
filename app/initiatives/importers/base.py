# initiatives/importers/base.py
#
# Shared data structures for all initiative importers.
# All parsers produce a ParsedImport; the view writes it to the DB.

from dataclasses import dataclass, field


@dataclass
class ParsedTurn:
    speaker: str          # "human" | "assistant"
    text: str
    timestamp: str | None = None
    username: str | None = None

    def to_dict(self) -> dict:
        return {
            "speaker": self.speaker,
            "username": self.username,
            "text": self.text,
            "timestamp": self.timestamp,
        }


@dataclass
class DetectedArtifact:
    kind: str             # decision | question | action | annotation | document
    title: str            # Short label surfaced in the preview UI
    body: str             # Longer content (may be empty for title-only items)
    source_turn_idx: int | None = None  # Which turn produced this

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "title": self.title,
            "body": self.body,
            "source_turn_idx": self.source_turn_idx,
        }


@dataclass
class ParsedImport:
    source_format: str        # "claude" | "chatgpt" | "freeform"
    conversation_title: str
    turns: list[ParsedTurn] = field(default_factory=list)
    detected_artifacts: list[DetectedArtifact] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def to_raw_transcript(self) -> list[dict]:
        """Returns the format expected by Session.raw_transcript."""
        return [t.to_dict() for t in self.turns]

    def to_artifact_dicts(self) -> list[dict]:
        return [a.to_dict() for a in self.detected_artifacts]

    def to_preview_dict(self) -> dict:
        """Serialisable dict for the preview API response."""
        return {
            "source_format": self.source_format,
            "conversation_title": self.conversation_title,
            "turns": self.to_raw_transcript(),
            "detected_artifacts": self.to_artifact_dicts(),
            "stats": self.stats,
        }


class ImportParseError(Exception):
    """Raised when a parser cannot make sense of the input."""
