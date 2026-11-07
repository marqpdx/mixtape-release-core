"""
Ariadne -- Cass to Crossroads result flow (build plan,
puddlejump/decisions/ariadne/build-plan-cass-to-crossroads-result-flow.md
§1-2, §6 piece 1).

Serializes one accessioned (CURATED) InquiryReview, and everything it
needs to render standalone on Crossroads, into a single JSON-safe dict.
Citations carry resolved source text at export time (CTO decision,
2026-11-07: denormalize into the existing `citations` JSONField rather
than modeling Passage/SourceDocument on Crossroads) -- Crossroads has
neither Cass's `Passage` table nor its corpus, so a `passage_id` alone
means nothing there.

`corpus_snapshot` is exported too, even though it isn't named in the
design note's §5.2/§5.4 -- `InquiryRun.corpus_snapshot` is a required
(non-null, PROTECT) FK, so importing a Run on Crossroads needs *some*
row to point at. The exported snapshot is a plain record (manifest hash
+ the list of Cass SourceRevision ids it covered), never dereferenced on
Crossroads; nothing there reads through it. This is the same
reuse-the-Cass-id-directly identity pattern already decided for
Inquiry/Run/Theme/Review (build plan §3), applied to a dependency that
pattern didn't originally name.
"""

from __future__ import annotations

from ariadne.models import InquiryReview, Passage

SCHEMA_VERSION = 1


def _resolve_citation_source(passage_id: str, passages: dict) -> dict | None:
    passage = passages.get(passage_id)
    if passage is None:
        return None
    document = passage.revision.document
    section = passage.section
    return {
        "passage_id": passage_id,
        "text": passage.text,
        "document_title": document.title,
        "document_uri": document.uri,
        "document_source_key": document.source_key,
        "revision_content_hash": passage.revision.content_hash,
        "revision_captured_at": passage.revision.captured_at.isoformat(),
        "section_heading_path": section.heading_path if section else None,
    }


def _export_citations(citations: list[dict]) -> list[dict]:
    all_passage_ids = {pid for c in citations for pid in c.get("passage_ids", [])}
    passages = {
        str(p.id): p
        for p in Passage.objects.filter(id__in=all_passage_ids).select_related(
            "revision__document", "section",
        )
    }
    exported = []
    for citation in citations:
        sources = [
            source
            for source in (
                _resolve_citation_source(pid, passages) for pid in citation.get("passage_ids", [])
            )
            if source is not None
        ]
        exported.append({**citation, "sources": sources})
    return exported


def build_review_export_package(review: InquiryReview) -> dict:
    """Only call this on a review where `status == InquiryReview.Status.CURATED`
    (build plan §6 piece 1; design note §5.3's "finished" signal) -- the
    caller (the management command) enforces that, this function trusts it."""

    inquiry = review.inquiry
    run = review.run
    snapshot = run.corpus_snapshot

    return {
        "schema_version": SCHEMA_VERSION,
        "inquiry": {
            "id": str(inquiry.id),
            "question": inquiry.question,
            "sub_questions": inquiry.sub_questions,
            "status": inquiry.status,
            "created_at": inquiry.created_at.isoformat(),
        },
        "corpus_snapshot": {
            "id": str(snapshot.id),
            "manifest_hash": snapshot.manifest_hash,
            "source_revision_ids": snapshot.source_revision_ids,
            "captured_at": snapshot.captured_at.isoformat(),
        },
        "run": {
            "id": str(run.id),
            "inquiry_id": str(inquiry.id),
            "corpus_snapshot_id": str(snapshot.id),
            "status": run.status,
            "model_versions": run.model_versions,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "created_at": run.created_at.isoformat(),
        },
        "themes": [
            {
                "id": str(theme.id),
                "run_id": str(run.id),
                "label": theme.label,
                "label_source": theme.label_source,
                "passage_ids": theme.passage_ids,
                "rank": theme.rank,
            }
            for theme in run.themes.order_by("rank")
        ],
        "review": {
            "id": str(review.id),
            "inquiry_id": str(inquiry.id),
            "run_id": str(run.id),
            "version": review.version,
            "body_markdown": review.body_markdown,
            "citations": _export_citations(review.citations),
            "uncited_claim_count": review.uncited_claim_count,
            "status": review.status,
            "draft_calls": review.draft_calls,
            "superseded_review_id": str(review.superseded_review_id) if review.superseded_review_id else None,
            "created_at": review.created_at.isoformat(),
        },
    }
