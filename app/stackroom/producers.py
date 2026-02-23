# stackroom/producers.py
"""
Activity producers for Puddlejump Canon events.

- Canon approval → notify group members
- Document checkout → notify group members
- Version submitted → notify admins
"""
from __future__ import annotations

from django.utils import timezone

from activity.producers import (
    _create_action_and_outbox,
    _ct,
    _ensure_activity_type,
    _id,
)


def on_canon_approved(*, approval, source_file, library):
    """Notify group members when a document is approved as Canon."""
    at = _ensure_activity_type(
        code="puddlejump.canon.approved",
        label="Document Approved as Canon",
        default_channel="system",
        default_priority="normal",
        suppressible=True,
    )
    _create_action_and_outbox(
        actor_content_type=_ct(approval.approved_by),
        actor_id=_id(approval.approved_by),
        actor_label="user",
        object_content_type=_ct(source_file),
        object_id=_id(source_file),
        context_content_type=_ct(library),
        context_id=_id(library),
        activity_type=at,
        verb="approved",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,
        metadata={
            "filename": source_file.filename,
            "version_number": approval.version.version_number,
            "library_title": library.title,
        },
        dedupe_key=f"{at.code}:{_id(approval)}",
        aggregate_key=f"canon:{_id(library)}",
        audience={
            "type": "group_members",
            "group_id": str(library.sponsor_object_id),
            "exclude_actor": True,
        },
        occurs_at=timezone.now(),
    )


def on_document_checked_out(*, source_file, user, library):
    """Notify group members when a document is checked out."""
    at = _ensure_activity_type(
        code="puddlejump.document.checked_out",
        label="Document Checked Out",
        default_channel="system",
        default_priority="low",
        suppressible=True,
    )
    _create_action_and_outbox(
        actor_content_type=_ct(user),
        actor_id=_id(user),
        actor_label="user",
        object_content_type=_ct(source_file),
        object_id=_id(source_file),
        context_content_type=_ct(library),
        context_id=_id(library),
        activity_type=at,
        verb="checked out",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,
        metadata={
            "filename": source_file.filename,
            "library_title": library.title,
        },
        dedupe_key=f"{at.code}:{_id(source_file)}:{_id(user)}",
        aggregate_key=f"checkout:{_id(library)}",
        audience={
            "type": "group_members",
            "group_id": str(library.sponsor_object_id),
            "exclude_actor": True,
        },
        occurs_at=timezone.now(),
    )


def on_version_submitted(*, version, source_file, library):
    """Notify admins when a new version is submitted for review."""
    at = _ensure_activity_type(
        code="puddlejump.version.submitted",
        label="New Version Submitted",
        default_channel="system",
        default_priority="normal",
        suppressible=True,
    )
    _create_action_and_outbox(
        actor_content_type=_ct(version.actor),
        actor_id=_id(version.actor),
        actor_label="user",
        object_content_type=_ct(source_file),
        object_id=_id(source_file),
        context_content_type=_ct(library),
        context_id=_id(library),
        activity_type=at,
        verb="submitted",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,
        metadata={
            "filename": source_file.filename,
            "version_number": version.version_number,
            "change_summary": version.change_summary[:200],
            "ai_assisted": version.ai_assisted,
            "library_title": library.title,
        },
        dedupe_key=f"{at.code}:{_id(version)}",
        aggregate_key=f"versions:{_id(library)}",
        audience={
            "type": "group_members",
            "group_id": str(library.sponsor_object_id),
            "exclude_actor": True,
        },
        occurs_at=timezone.now(),
    )
