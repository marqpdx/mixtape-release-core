# stackroom/services/canon_service.py
"""
Canon governance service (Puddlejump v1 Sections 4-6, Appendix A1/A4).

Handles:
- Version submission (append-only history)
- Canon approval (synchronous, export-ready immediately)
- Soft checkout (advisory, not enforced)
- Diff retrieval for approval UI
"""
from __future__ import annotations

import hashlib

from django.db import transaction
from django.utils import timezone

from stackroom.models import SourceFile, SourceFileVersion, CanonApproval


# ---------------------------------------------------------------------------
# Version management
# ---------------------------------------------------------------------------

@transaction.atomic
def submit_version(
    source_file: SourceFile,
    content: str,
    actor,
    change_summary: str = "",
    ai_assisted: bool = False,
    ai_agent: str = "",
    ai_summary: str = "",
) -> SourceFileVersion:
    """
    Create a new version record for a SourceFile.

    After canonization, every edit creates a version entry (§5).
    Also usable pre-canon for initial version tracking.
    """
    # Auto-increment version number — select_for_update locks the latest row
    # to prevent two concurrent submissions racing to the same version number
    last_version = (
        SourceFileVersion.objects
        .select_for_update()
        .filter(source_file=source_file)
        .order_by('-version_number')
        .first()
    )
    next_number = (last_version.version_number + 1) if last_version else 1

    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    version = SourceFileVersion.objects.create(
        source_file=source_file,
        version_number=next_number,
        hash_sha256=content_hash,
        content_snapshot=content,
        change_summary=change_summary,
        actor=actor,
        ai_assisted=ai_assisted,
        ai_agent=ai_agent,
        ai_summary=ai_summary,
    )

    # Update the SourceFile hash to reflect current content
    source_file.hash_sha256 = content_hash
    source_file.save(update_fields=["hash_sha256", "updated_at"])

    return version


def get_version_history(source_file: SourceFile):
    """
    Return ordered version list with approval status.
    """
    versions = (
        SourceFileVersion.objects
        .filter(source_file=source_file)
        .select_related("actor")
        .order_by("-version_number")
    )

    # Fetch all approvals for this file in one query, keyed by version_id
    approvals_by_version = {
        a.version_id: a
        for a in CanonApproval.objects
        .filter(source_file=source_file)
        .select_related("approved_by")
    }

    result = []
    for v in versions:
        approval = approvals_by_version.get(v.id)

        result.append({
            "id": str(v.id),
            "version_number": v.version_number,
            "hash_sha256": v.hash_sha256,
            "change_summary": v.change_summary,
            "actor": {
                "id": str(v.actor.id) if v.actor else None,
                "username": v.actor.username if v.actor else None,
                "display_name": getattr(v.actor, "display_name", v.actor.username) if v.actor else None,
            },
            "ai_assisted": v.ai_assisted,
            "ai_agent": v.ai_agent or None,
            "ai_summary": v.ai_summary or None,
            "is_approved": v.id in approvals_by_version,
            "approved_by": {
                "username": approval.approved_by.username,
                "display_name": getattr(approval.approved_by, "display_name", approval.approved_by.username),
            } if approval and approval.approved_by else None,
            "approved_at": approval.approved_at.isoformat() if approval else None,
            "created_at": v.created_at.isoformat(),
        })

    return result


# ---------------------------------------------------------------------------
# Canon approval
# ---------------------------------------------------------------------------

@transaction.atomic
def approve_canon(
    source_file: SourceFile,
    version: SourceFileVersion,
    approved_by,
    notes: str = "",
) -> CanonApproval:
    """
    Approve a version as Canon (§4).

    This is synchronous — export-ready immediately after return (A4).
    Ingestion re-trigger should be called asynchronously after this.
    """
    approval = CanonApproval.objects.create(
        source_file=source_file,
        version=version,
        approved_by=approved_by,
        notes=notes,
    )

    # Set canon status on SourceFile
    source_file.is_canon = True
    source_file.canon_version = version
    source_file.save(update_fields=["is_canon", "canon_version", "updated_at"])

    # Update LibraryItem canonical metadata
    from stackroom.models import LibraryItem
    from django.contrib.contenttypes.models import ContentType

    sf_ct = ContentType.objects.get_for_model(SourceFile)
    LibraryItem.objects.filter(
        library=source_file.library,
        content_type=sf_ct,
        content_object_id=source_file.id,
    ).update(
        is_featured=True,
        puddlejump_canonical_metadata={
            "canonical_date": timezone.now().strftime("%Y-%m-%d"),
            "canonical_authority": getattr(approved_by, "username", str(approved_by)),
            "review_date": "",
        },
    )

    return approval


# ---------------------------------------------------------------------------
# Diff for approval UI
# ---------------------------------------------------------------------------

def get_diff_versions(source_file: SourceFile) -> dict:
    """
    Return previous Canon content and latest version content for two-way diff (A6).

    Returns:
        {
            "previous_content": str | None,
            "proposed_content": str,
            "previous_version_number": int | None,
            "proposed_version_number": int,
        }
    """
    latest_version = (
        SourceFileVersion.objects
        .filter(source_file=source_file)
        .order_by("-version_number")
        .first()
    )

    if not latest_version:
        return {
            "previous_content": None,
            "proposed_content": "",
            "previous_version_number": None,
            "proposed_version_number": 0,
        }

    previous_content = None
    previous_version_number = None

    if source_file.canon_version and source_file.canon_version != latest_version:
        previous_content = source_file.canon_version.content_snapshot
        previous_version_number = source_file.canon_version.version_number

    return {
        "previous_content": previous_content,
        "proposed_content": latest_version.content_snapshot,
        "previous_version_number": previous_version_number,
        "proposed_version_number": latest_version.version_number,
    }


# ---------------------------------------------------------------------------
# Soft checkout (§6, A1)
# ---------------------------------------------------------------------------

@transaction.atomic
def checkout(source_file: SourceFile, user) -> SourceFile:
    """Check out a document (advisory only, no hard locking)."""
    source_file.checked_out_by = user
    source_file.checked_out_at = timezone.now()
    source_file.save(update_fields=["checked_out_by", "checked_out_at", "updated_at"])
    return source_file


@transaction.atomic
def checkin(source_file: SourceFile, user) -> SourceFile:
    """Release a checkout. Any user can release (soft governance)."""
    source_file.checked_out_by = None
    source_file.checked_out_at = None
    source_file.save(update_fields=["checked_out_by", "checked_out_at", "updated_at"])
    return source_file


def get_checkout_status(source_file: SourceFile, request_user=None) -> dict | None:
    """Return checkout info or None if not checked out."""
    if not source_file.checked_out_by:
        return None
    return {
        "checked_out_by": {
            "username": source_file.checked_out_by.username,
            "display_name": getattr(
                source_file.checked_out_by, "display_name",
                source_file.checked_out_by.username
            ),
        },
        "checked_out_at": source_file.checked_out_at.isoformat() if source_file.checked_out_at else None,
        "is_own": request_user is not None and source_file.checked_out_by_id == request_user.id,
    }
