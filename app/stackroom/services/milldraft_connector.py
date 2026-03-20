# stackroom/services/milldraft_connector.py
#
# Stackroom → MillDraft Connector
#
# When a Stackroom Artifact finishes processing, this connector creates a
# MillDraft candidate and a MillDraftSuggestion record so the content surfaces
# in the Review Queue for steward triage.
#
# Design rules:
# - Idempotent: if a suggestion already exists for this artifact, skip.
# - Sponsor chain: MillDraft inherits the library's sponsor (Group or User).
# - Content profile: defaults to "writing"; can be overridden per library scope.
# - Grist body: populated from Artifact.text (the extracted text).
# - Summary: populated from Artifact.interior_summary if available.
# - Provenance bundle: carries artifact_id, source_file_id, library_id.

import logging
from typing import Optional

from django.db import transaction

logger = logging.getLogger(__name__)

# Scope → content_profile mapping (extend as more profiles are built out)
_SCOPE_TO_PROFILE = {
    "writing": "writing",
    "general": "writing",   # Default until more profiles exist
}


@transaction.atomic
def create_milldraft_from_artifact(
    artifact_id: str,
    content_profile: Optional[str] = None,
) -> Optional[dict]:
    """
    Create a MillDraft candidate from a fully-processed Stackroom Artifact.

    Idempotent: returns None (no-op) if a MillDraftSuggestion already exists
    for this artifact.

    Args:
        artifact_id:     UUID string of the Stackroom Artifact.
        content_profile: Override content profile (defaults to library scope
                         mapping, falling back to "writing").

    Returns:
        Dict with draft_id and suggestion_id on creation, None if already exists.
    """
    from stackroom.models import Artifact
    from fundamentals.models import (
        MillDraft,
        MillDraftStatus,
        MillDraftSuggestion,
        SuggestionSource,
    )

    # --- Fetch artifact ---
    try:
        artifact = Artifact.objects.select_related(
            "source_file__library__sponsor_content_type"
        ).get(id=artifact_id)
    except Artifact.DoesNotExist:
        logger.error("milldraft_connector: Artifact %s not found", artifact_id)
        return None

    # --- Idempotency check ---
    if MillDraftSuggestion.objects.filter(
        source_system=SuggestionSource.STACKROOM,
        source_ref=str(artifact.id),
    ).exists():
        logger.debug(
            "milldraft_connector: suggestion already exists for artifact %s — skipping",
            artifact_id,
        )
        return None

    # --- Resolve sponsor from library ---
    library = artifact.source_file.library
    sponsor_ct = library.sponsor_content_type
    sponsor_id = library.sponsor_object_id

    # --- Resolve content profile ---
    resolved_profile = (
        content_profile
        or _SCOPE_TO_PROFILE.get(library.scope, "writing")
    )

    # --- Build draft content from artifact ---
    title = _extract_title(artifact, library)
    summary = artifact.interior_summary or ""
    grist_body = artifact.text or ""

    provenance_bundle = {
        "source": "stackroom",
        "artifact_id": str(artifact.id),
        "artifact_type": artifact.artifact_type,
        "source_file_id": str(artifact.source_file.id),
        "source_file_name": artifact.source_file.filename,
        "library_id": str(library.id),
        "library_title": library.title,
        "keywords": artifact.keywords or [],
    }

    # --- Create MillDraft ---
    draft = MillDraft.objects.create(
        sponsor_content_type=sponsor_ct,
        sponsor_object_id=sponsor_id,
        content_profile=resolved_profile,
        status=MillDraftStatus.CANDIDATE,
        title=title,
        summary=summary,
        grist_body=grist_body,
        source_type="stackroom",
        source_id=str(artifact.id),
        provenance_bundle=provenance_bundle,
    )

    # --- Create MillDraftSuggestion ---
    suggestion = MillDraftSuggestion.objects.create(
        draft=draft,
        source_system=SuggestionSource.STACKROOM,
        source_ref=str(artifact.id),
        raw_payload={
            "artifact_id": str(artifact.id),
            "artifact_type": artifact.artifact_type,
            "source_file_id": str(artifact.source_file.id),
            "filename": artifact.source_file.filename,
            "library_id": str(library.id),
            "interior_summary": artifact.interior_summary or "",
            "keywords": artifact.keywords or [],
            "text_length": len(artifact.text or ""),
        },
        score=None,  # Stackroom doesn't produce a relevance score at ingest time
    )

    logger.info(
        "milldraft_connector: created MillDraft %s and suggestion %s "
        "from artifact %s (library: %s)",
        draft.id,
        suggestion.id,
        artifact_id,
        library.title,
    )

    return {
        "draft_id": str(draft.id),
        "suggestion_id": str(suggestion.id),
    }


def _extract_title(artifact, library) -> str:
    """
    Best-effort title extraction from artifact metadata.

    Priority:
    1. interior_summary first sentence (if short enough)
    2. Source file filename (stripped of extension)
    3. Library title as fallback
    """
    if artifact.interior_summary:
        # Take first sentence if it's a reasonable title length
        first_sentence = artifact.interior_summary.split(".")[0].strip()
        if 10 < len(first_sentence) <= 120:
            return first_sentence

    filename = artifact.source_file.filename
    if filename:
        # Strip extension and clean up
        name = filename.rsplit(".", 1)[0]
        name = name.replace("_", " ").replace("-", " ").strip()
        if name:
            return name[:120]

    return library.title or "Untitled"
