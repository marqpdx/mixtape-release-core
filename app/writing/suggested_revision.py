from typing import Any

from django.db import transaction

from writing.fidelity_report import create_fidelity_report
from writing.models import WritingAnalysisSession, WritingPiece, WritingSuggestedRevision, WorkingDocument


def build_body_json_from_export(export_payload: dict[str, Any]) -> dict[str, Any]:
    blocks = ((export_payload or {}).get("document") or {}).get("blocks") or []
    content = [block.get("node_json") for block in blocks if block.get("node_json")]
    return {
        "type": "doc",
        "content": content,
    }


def build_suggested_revision_title(*, source_title: str, suffix: str) -> str:
    base = (source_title or "").strip() or "Untitled"
    resolved_suffix = (suffix or "").strip() or "Suggested Revision"
    return f"{base} - {resolved_suffix}"


def create_suggested_revision_from_session(*, session: WritingAnalysisSession, acting_user, title_suffix: str = "Suggested Revision"):
    source_piece = session.source_piece
    export_payload = session.export_payload or {}
    piece_payload = export_payload.get("piece") or {}
    source_title = piece_payload.get("title") or source_piece.title or ""
    source_excerpt = piece_payload.get("excerpt") or source_piece.excerpt or ""
    body_json = build_body_json_from_export(export_payload)

    with transaction.atomic():
        suggested_piece = WritingPiece(
            author=source_piece.author,
            author_name=source_piece.author_name or (
                source_piece.author.get_full_name() or source_piece.author.username
                if source_piece.author else ""
            ),
            title=build_suggested_revision_title(source_title=source_title, suffix=title_suffix),
            excerpt=source_excerpt,
            body_json=body_json,
            writing_kind=source_piece.writing_kind,
            addressed_to=source_piece.addressed_to,
            enable_outline=source_piece.enable_outline,
            status="draft",
            canonical_url=source_piece.canonical_url,
            series=source_piece.series,
            series_order=source_piece.series_order,
            target_wordcount=source_piece.target_wordcount,
            suggest_splits=source_piece.suggest_splits,
            allow_comments=source_piece.allow_comments,
        )
        suggested_piece.set_sponsor(source_piece.sponsor)
        suggested_piece.set_submitted_by(acting_user)
        suggested_piece.save()

        WorkingDocument.objects.create(
            piece=suggested_piece,
            user=acting_user,
            title=suggested_piece.title,
            excerpt=suggested_piece.excerpt,
            body_json=suggested_piece.body_json,
        )

        suggested_revision = WritingSuggestedRevision.objects.create(
            source_piece=source_piece,
            suggested_piece=suggested_piece,
            analysis_session=session,
            source_revision_hash=session.source_revision_hash,
            derivation_type=WritingSuggestedRevision.DerivationType.SUGGESTED_REVISION,
            created_by=acting_user,
        )

        fidelity_report = create_fidelity_report(session=session, suggested_revision=suggested_revision)

        session.status = WritingAnalysisSession.Status.IMPORTED
        session.completed_at = session.completed_at or suggested_revision.created_at
        session.save(update_fields=["status", "completed_at", "updated_at"])

    return suggested_piece, suggested_revision, fidelity_report
