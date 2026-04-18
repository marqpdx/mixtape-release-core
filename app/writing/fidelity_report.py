from typing import Any

from writing.models import WritingAnalysisSession, WritingFidelityReport, WritingSuggestedRevision


def build_fidelity_report_payload(*, session: WritingAnalysisSession, suggested_revision: WritingSuggestedRevision) -> dict[str, Any]:
    export_payload = session.export_payload or {}
    source_blocks = ((export_payload.get("document") or {}).get("blocks")) or []
    source_block_ids = [block.get("block_id") for block in source_blocks if block.get("block_id")]
    source_word_count = sum(int(block.get("word_count") or 0) for block in source_blocks)
    source_section_count = len(((export_payload.get("outline") or {}).get("detected_headings")) or [])

    return {
        "version": WritingFidelityReport.REPORT_VERSION_V1,
        "analysis_session_id": str(session.id),
        "source_piece_id": str(suggested_revision.source_piece_id),
        "suggested_piece_id": str(suggested_revision.suggested_piece_id),
        "source_revision_hash": session.source_revision_hash,
        "summary": {
            "source_word_count": source_word_count,
            "suggested_word_count": source_word_count,
            "source_section_count": source_section_count,
            "suggested_section_count": source_section_count,
            "unchanged_block_count": len(source_block_ids),
            "edited_block_count": 0,
            "moved_block_count": 0,
            "added_block_count": 0,
            "removed_block_count": 0,
        },
        "structural_changes": [],
        "textual_changes": [],
        "warnings": [],
    }


def create_fidelity_report(*, session: WritingAnalysisSession, suggested_revision: WritingSuggestedRevision) -> WritingFidelityReport:
    payload = build_fidelity_report_payload(session=session, suggested_revision=suggested_revision)
    return WritingFidelityReport.objects.create(
        analysis_session=session,
        suggested_revision=suggested_revision,
        source_piece=suggested_revision.source_piece,
        suggested_piece=suggested_revision.suggested_piece,
        source_revision_hash=session.source_revision_hash,
        report_version=WritingFidelityReport.REPORT_VERSION_V1,
        report_payload=payload,
    )
