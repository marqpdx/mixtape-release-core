# publishing/services/content_display.py

"""
Content Display Service

Resolves ContentPlacement to displayable artifacts with metadata.
Handles follow_updates vs locked artifact logic.
"""

from typing import Dict, Any, Optional
from django.core.exceptions import ValidationError


def get_display_payload(placement) -> Dict[str, Any]:
    """
    Resolve a ContentPlacement to its displayable artifact.

    Resolution order:
    1. If locked_artifact exists → use it
    2. Else if follow_updates=True → source.get_current_artifact()
    3. Else → ValidationError (should be prevented by model validation)

    Args:
        placement: ContentPlacement instance

    Returns:
        dict with keys:
            - artifact: The resolved artifact (WritingVersion, DispatchSnapshot, etc.)
            - source: The source content object (WritingPiece, DispatchContent, etc.)
            - metadata: Display metadata (title, excerpt, overrides, etc.)

    Raises:
        ValidationError: If placement configuration is invalid
    """
    from publishing.models import ContentPlacement

    if not isinstance(placement, ContentPlacement):
        raise TypeError(f"Expected ContentPlacement, got {type(placement)}")

    # Resolve artifact
    artifact = None

    if placement.locked_artifact:
        # Use locked artifact
        artifact = placement.locked_artifact
    elif placement.follow_updates:
        # Get current artifact from source
        source = placement.source
        if not source:
            raise ValidationError(f"Placement {placement.id} has no source")

        if not hasattr(source, 'get_current_artifact'):
            raise ValidationError(
                f"Source {source.__class__.__name__} does not implement get_current_artifact()"
            )

        artifact = source.get_current_artifact()

        if not artifact:
            raise ValidationError(
                f"Source {source.__class__.__name__} has no current artifact"
            )
    else:
        # Should not happen due to model validation
        raise ValidationError(
            "Placement must either have locked_artifact or follow_updates=True"
        )

    # Build metadata
    metadata = _build_display_metadata(placement, artifact)

    return {
        'artifact': artifact,
        'source': placement.source,
        'placement': placement,
        'metadata': metadata,
    }


def _build_display_metadata(placement, artifact) -> Dict[str, Any]:
    """
    Build display metadata for a placement.

    Applies overrides from placement.overrides to artifact data.
    Handles fragment_selector for excerpts.

    Args:
        placement: ContentPlacement instance
        artifact: Resolved artifact (WritingVersion, DispatchSnapshot, etc.)

    Returns:
        dict with display metadata
    """
    metadata = {
        'channel': placement.channel,
        'visibility': placement.visibility,
        'is_excerpt': placement.is_excerpt,
    }

    # Get artifact content
    # Most artifacts have body_json
    if hasattr(artifact, 'body_json'):
        metadata['body_json'] = artifact.body_json

    # Get base title and excerpt from artifact
    if hasattr(artifact, 'title'):
        metadata['title'] = artifact.title
    if hasattr(artifact, 'excerpt'):
        metadata['excerpt'] = artifact.excerpt

    # Apply overrides from placement
    overrides = placement.overrides or {}
    if overrides.get('title'):
        metadata['title'] = overrides['title']
    if overrides.get('excerpt'):
        metadata['excerpt'] = overrides['excerpt']
    if overrides.get('cover_image'):
        metadata['cover_image'] = overrides['cover_image']
    if overrides.get('subject'):
        metadata['subject'] = overrides['subject']

    # Channel-specific overrides
    if placement.channel == 'lantern' and overrides.get('lantern_subject'):
        metadata['lantern_subject'] = overrides['lantern_subject']

    # Fragment selector for excerpts
    if placement.is_excerpt and placement.fragment_selector:
        metadata['fragment_selector'] = placement.fragment_selector
        # Note: Actual fragment extraction would happen in the frontend
        # or in a separate service function

    return metadata


def get_placement_content(placement) -> Optional[Dict[str, Any]]:
    """
    Convenience function to get displayable content from a placement.
    Returns None if placement cannot be resolved.

    Args:
        placement: ContentPlacement instance

    Returns:
        Display payload dict or None if resolution fails
    """
    try:
        return get_display_payload(placement)
    except (ValidationError, AttributeError):
        return None


def resolve_artifact_for_source(source, locked_artifact_id=None):
    """
    Resolve which artifact to use for a given source.

    Args:
        source: Source content object (WritingPiece, DispatchContent, etc.)
        locked_artifact_id: Optional UUID to lock to specific artifact

    Returns:
        Artifact instance or None
    """
    if locked_artifact_id:
        # Try to get specific artifact
        if hasattr(source, 'get_artifact'):
            try:
                return source.get_artifact(locked_artifact_id)
            except Exception:
                pass
        return None

    # Get current artifact
    if hasattr(source, 'get_current_artifact'):
        return source.get_current_artifact()

    return None
