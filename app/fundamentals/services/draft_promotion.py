# fundamentals/services/draft_promotion.py
#
# Draft Promotion Service — Phase 4 Workbench
#
# Promotes a MillDraft to a canonical content object (WritingPiece, Event, etc.)
# with Publish Safety Class (PSC) enforcement.
#
# PSC-0 (default): Promote creates a draft canonical object; publish is separate.
# PSC-1 (conditional): Promote + Publish allowed if safety checks pass.
# PSC-2 (rare): Promote implies publish (admin/system domains only).
#
# Profile dispatch:
#   "writing" → WritingPiece (draft or published based on PSC)
#   all others → NotImplementedError (stubs added as profiles are built out)

from dataclasses import dataclass
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

User = get_user_model()


# ============================================================================
# Errors
# ============================================================================

class PromotionError(Exception):
    """Raised when promotion cannot proceed."""
    pass


class ValidationError(PromotionError):
    """Raised when hard validation blocks promotion."""
    def __init__(self, message: str, validation_errors: list | None = None):
        super().__init__(message)
        self.validation_errors = validation_errors or []


class PSCViolation(PromotionError):
    """Raised when requested publish action violates PSC rules."""
    pass


class UnsupportedProfile(PromotionError):
    """Raised when no promotion handler exists for a content profile."""
    pass


# ============================================================================
# Result
# ============================================================================

@dataclass
class PromotionResult:
    """Returned from promote_draft() on success."""
    canonical_object: Any       # The created or updated canonical object
    canonical_type: str         # Model name, e.g. "writingpiece"
    was_published: bool         # True if published (not just draft)
    draft_id: str               # UUID string of the source MillDraft


# ============================================================================
# PSC Safety Checks
# ============================================================================

def _psc1_safety_checks(draft) -> list[str]:
    """
    Safety checks required before PSC-1 publish.
    Returns a list of failure messages (empty = all clear).
    """
    failures = []
    if not draft.title or not draft.title.strip():
        failures.append("Title is required for publish.")
    if not draft.grist_body or not draft.grist_body.strip():
        failures.append("Content body (grist) is required for publish.")
    if draft.ast is None:
        failures.append("Structured content (AST) is required for publish.")
    return failures


# ============================================================================
# Profile Handlers
# ============================================================================

def _promote_writing(draft, promoted_by: User, publish: bool) -> tuple[Any, bool]:
    """
    Promote a MillDraft with content_profile="writing" to a WritingPiece.

    Returns (writing_piece, was_published).
    """
    from writing.models import WritingPiece
    from writing.choices import ContentStatus

    # Resolve sponsor from the MillDraft
    sponsor_ct = draft.sponsor_content_type
    sponsor_id = draft.sponsor_object_id

    # Author resolution: prefer draft.author, fall back to promoted_by
    author = draft.author if draft.author_id else promoted_by

    # Build body_json from AST (TipTap-compatible) or fall back to empty doc
    body_json = draft.ast if draft.ast else {"type": "doc", "content": []}

    # Determine final publish status
    was_published = publish
    status = ContentStatus.PUBLISHED if publish else ContentStatus.DRAFT

    piece = WritingPiece.objects.create(
        sponsor_content_type=sponsor_ct,
        sponsor_object_id=sponsor_id,
        author=author,
        title=draft.title or "Untitled",
        summary=draft.summary or "",
        body_json=body_json,
        writing_kind="post",
        status=status,
        published_at=timezone.now() if publish else None,
    )

    return piece, was_published


# Profile dispatch table — add new profiles here as they are built out
_PROFILE_HANDLERS = {
    "writing": _promote_writing,
}


# ============================================================================
# Main Entry Point
# ============================================================================

@transaction.atomic
def promote_draft(draft, promoted_by: User, publish: bool = False) -> PromotionResult:
    """
    Promote a MillDraft to a canonical content object.

    Args:
        draft:        MillDraft instance (must be in active or ready_to_promote state)
        promoted_by:  User performing the promotion
        publish:      If True, attempt to publish immediately (subject to PSC rules)

    Returns:
        PromotionResult with the created canonical object.

    Raises:
        ValidationError:    Hard validation failed (missing AST, title, etc.)
        PSCViolation:       Requested publish action blocked by PSC rules
        UnsupportedProfile: No handler registered for this content_profile
        PromotionError:     Other promotion failure
    """
    from fundamentals.models import MillDraftStatus, ContentProfileConfig

    # --- Pre-flight: state check ---
    if draft.status not in (MillDraftStatus.ACTIVE, MillDraftStatus.READY_TO_PROMOTE):
        raise PromotionError(
            f"Draft must be active or ready_to_promote to promote "
            f"(current: {draft.status})."
        )

    # --- Hard validation ---
    draft.run_validation(hard=True)
    if not draft.is_valid:
        raise ValidationError(
            "Draft failed hard validation and cannot be promoted.",
            validation_errors=draft.validation_errors,
        )

    # --- PSC enforcement ---
    try:
        profile_config = ContentProfileConfig.objects.get(
            profile_name=draft.content_profile
        )
        psc = profile_config.publish_safety_class
    except ContentProfileConfig.DoesNotExist:
        # Default to PSC-0 if no profile config exists yet
        psc = "psc_0"

    effective_publish = False
    if publish:
        if psc == "psc_0":
            raise PSCViolation(
                f"Profile '{draft.content_profile}' is PSC-0 — "
                "publish must be performed as a separate step after promotion."
            )
        elif psc == "psc_1":
            failures = _psc1_safety_checks(draft)
            if failures:
                raise PSCViolation(
                    "PSC-1 safety checks failed: " + "; ".join(failures)
                )
            effective_publish = True
        elif psc == "psc_2":
            effective_publish = True

    # --- Profile dispatch ---
    handler = _PROFILE_HANDLERS.get(draft.content_profile)
    if handler is None:
        raise UnsupportedProfile(
            f"No promotion handler for content_profile='{draft.content_profile}'. "
            f"Supported: {sorted(_PROFILE_HANDLERS.keys())}"
        )

    canonical_object, was_published = handler(draft, promoted_by, effective_publish)

    # --- Link draft back to canonical object ---
    canonical_ct = ContentType.objects.get_for_model(canonical_object)
    draft.canonical_content_type = canonical_ct
    draft.canonical_object_id = canonical_object.pk
    draft.save(update_fields=["canonical_content_type", "canonical_object_id", "updated_at"])

    # --- Transition state machine ---
    # Ensure the draft is in ready_to_promote before the final transition
    if draft.status == MillDraftStatus.ACTIVE:
        draft.mark_ready_to_promote()

    draft.promote(user=promoted_by)

    return PromotionResult(
        canonical_object=canonical_object,
        canonical_type=canonical_ct.model,
        was_published=was_published,
        draft_id=str(draft.id),
    )
