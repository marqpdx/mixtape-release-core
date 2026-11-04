# atrium/distill.py
"""Guidance for each kind of Distillate, used by run_distill (atrium/tasks)."""

from atrium.models import DistillateDocumentType

DOCUMENT_TYPE_GUIDANCE = {
    DistillateDocumentType.FIELD_NOTE: (
        "A field note is a short (1-3 paragraphs), direct record of what was observed, "
        "decided, or learned. First-person voice. What happened, what was noticed, what's next."
    ),
    DistillateDocumentType.FINDING: (
        "A finding states a conclusion derived from evidence. Structured: Background, "
        "Evidence, Finding, Implication. Precise and factual — no hedging."
    ),
    DistillateDocumentType.POSITION_PAPER: (
        "A position paper argues for a specific approach or decision. Structured: "
        "Context, Position, Rationale, Trade-offs, Recommendation."
    ),
    DistillateDocumentType.DRAFT_ADR: (
        "An ADR (Architecture Decision Record) documents a decision and its context. "
        "Sections: Status (Draft), Context, Decision, Consequences."
    ),
    DistillateDocumentType.SUMMARY: (
        "A summary captures the key points, decisions, and open questions from the session "
        "in 2-4 paragraphs. Concise and scannable — bullet lists welcome."
    ),
    DistillateDocumentType.OTHER: (
        "Produce a clear, well-structured document that captures the key substance of the session."
    ),
}
