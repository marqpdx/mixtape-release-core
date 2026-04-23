from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from .signals import SIGNAL_MARKER_NAMES, SIGNAL_MARKER_REGISTRY

STALE_DRAFT_DAYS = 30
ORIENTATION_LIMIT = 5
REENTRY_LIMIT = 7


# ---------------------------------------------------------------------------
# Re-entry
# ---------------------------------------------------------------------------

def get_reentry_items(user):
    """
    Mix of recently-read pieces (ReadingStats.last_read_at) and open drafts
    (WritingPiece status=draft), ordered by recency, capped at REENTRY_LIMIT.
    """
    from reading.models import ReadingStats
    from writing.models import WritingPiece

    items = []

    # Recent reads
    stats = (
        ReadingStats.objects
        .filter(user=user, last_read_at__isnull=False)
        .select_related("artifact")
        .order_by("-last_read_at")[:REENTRY_LIMIT]
    )
    for s in stats:
        piece = s.artifact
        items.append({
            "kind": "reading",
            "id": str(piece.id),
            "title": piece.title or "",
            "slug": piece.slug or "",
            "status": piece.status,
            "recency": s.last_read_at,
        })

    # Open drafts authored by user (not already in reads)
    read_ids = {i["id"] for i in items}
    drafts = (
        WritingPiece.objects
        .filter(author=user, status="draft")
        .order_by("-updated_at")[:REENTRY_LIMIT]
    )
    for d in drafts:
        if str(d.id) not in read_ids:
            items.append({
                "kind": "draft",
                "id": str(d.id),
                "title": d.title or "",
                "slug": d.slug or "",
                "status": d.status,
                "recency": d.updated_at,
            })

    items.sort(key=lambda x: x["recency"], reverse=True)
    # Strip internal recency key before returning
    for item in items:
        item.pop("recency")
    return items[:REENTRY_LIMIT]


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

def get_signals(user):
    """
    Aggregate /! /~ /? /@ markers from WritingMarkerOccurrence (pieces authored
    by the user), flagged Darts, and ReadingStats.flagged_to_reread.
    """
    from atelier.models import WritingMarkerOccurrence
    from reading.models import Dart, ReadingStats

    # Markers on the user's own pieces, grouped by raw_name
    markers_qs = (
        WritingMarkerOccurrence.objects
        .filter(
            piece__author=user,
            raw_name__in=SIGNAL_MARKER_NAMES,
            status=WritingMarkerOccurrence.STATUS_PENDING,
        )
        .select_related("piece")
        .order_by("raw_name", "-created_at")
    )

    marker_groups = {}
    for m in markers_qs:
        name = m.raw_name
        if name not in marker_groups:
            meta = SIGNAL_MARKER_REGISTRY[name]
            marker_groups[name] = {
                "signal": meta["slug"],
                "label": meta["label"],
                "symbol": meta["symbol"],
                "items": [],
            }
        marker_groups[name]["items"].append({
            "id": str(m.id),
            "piece_id": str(m.piece_id),
            "piece_title": m.piece.title or "",
            "piece_slug": m.piece.slug or "",
            "label": m.label,
            "body": m.body,
            "status": m.status,
            "created_at": m.created_at.isoformat(),
        })

    # Flagged Darts
    darts = (
        Dart.objects
        .filter(user=user, is_flagged=True)
        .select_related("artifact")
        .order_by("-created_at")[:20]
    )
    flagged_darts = [
        {
            "id": str(d.id),
            "piece_id": str(d.artifact_id),
            "piece_title": d.artifact.title or "",
            "piece_slug": d.artifact.slug or "",
            "note_text": d.note_text,
            "selected_text": d.selected_text or "",
            "created_at": d.created_at.isoformat(),
        }
        for d in darts
    ]

    # Flagged-to-reread
    reread_stats = (
        ReadingStats.objects
        .filter(user=user, flagged_to_reread=True)
        .select_related("artifact")
        .order_by("-updated_at")[:20]
    )
    flagged_rereads = [
        {
            "id": str(s.id),
            "piece_id": str(s.artifact_id),
            "piece_title": s.artifact.title or "",
            "piece_slug": s.artifact.slug or "",
            "last_read_at": s.last_read_at.isoformat() if s.last_read_at else None,
        }
        for s in reread_stats
    ]

    return {
        "markers": list(marker_groups.values()),
        "flagged_darts": flagged_darts,
        "flagged_rereads": flagged_rereads,
    }


# ---------------------------------------------------------------------------
# Orientation
# ---------------------------------------------------------------------------

def get_orientation(user):
    """
    Active-gravity initiatives (created by user, active/simmering) and groups
    (where user is an active member), ordered by most-recent activity, top 5 each.
    """
    from django.contrib.contenttypes.models import ContentType
    from groups.models.membership import GroupMembership
    from initiatives.models import Initiative, InitiativeStatus

    # Initiatives
    active_statuses = [InitiativeStatus.ACTIVE, InitiativeStatus.SIMMERING]
    initiatives_qs = (
        Initiative.objects
        .filter(created_by=user, status__in=active_statuses)
        .order_by("-updated_at")[:ORIENTATION_LIMIT]
    )
    initiatives = [
        {
            "id": str(i.id),
            "title": i.title,
            "status": i.status,
            "updated_at": i.updated_at.isoformat(),
        }
        for i in initiatives_qs
    ]

    # Groups
    user_ct = ContentType.objects.get_for_model(user)
    memberships = (
        GroupMembership.objects
        .filter(
            member_content_type=user_ct,
            member_object_id=user.id,
            is_active=True,
        )
        .select_related("group")
        .order_by("-group__updated_at")[:ORIENTATION_LIMIT]
    )
    groups = [
        {
            "id": str(m.group.id),
            "title": m.group.title,
            "slug": m.group.slug,
            "group_type": m.group.group_type,
            "updated_at": m.group.updated_at.isoformat(),
        }
        for m in memberships
    ]

    return {
        "initiatives": initiatives,
        "groups": groups,
    }


# ---------------------------------------------------------------------------
# Stewardship
# ---------------------------------------------------------------------------

def get_stewardship(user):
    """
    Stale drafts (>30 days without edit), overdue reminders, and unresolved /?
    markers on the user's pieces.
    """
    from initiatives.models import Reminder, ReminderStatus
    from writing.models import WritingPiece
    from atelier.models import WritingMarkerOccurrence

    cutoff = timezone.now() - timedelta(days=STALE_DRAFT_DAYS)
    now = timezone.now()

    # Stale drafts
    stale_drafts_qs = (
        WritingPiece.objects
        .filter(author=user, status="draft", updated_at__lt=cutoff)
        .order_by("updated_at")[:20]
    )
    stale_drafts = [
        {
            "id": str(p.id),
            "title": p.title or "",
            "slug": p.slug or "",
            "updated_at": p.updated_at.isoformat(),
            "days_stale": (now - p.updated_at).days,
        }
        for p in stale_drafts_qs
    ]

    # Overdue reminders (remind_at in the past, not acknowledged)
    user_ct = ContentType.objects.get_for_model(user)
    overdue_reminders_qs = (
        Reminder.objects
        .filter(
            sponsor_content_type=user_ct,
            sponsor_object_id=user.id,
            remind_at__lt=now,
            status=ReminderStatus.PENDING,
        )
        .order_by("remind_at")[:20]
    )
    overdue_reminders = [
        {
            "id": str(r.id),
            "title": r.title,
            "body": r.body,
            "remind_at": r.remind_at.isoformat(),
            "days_overdue": (now - r.remind_at).days,
        }
        for r in overdue_reminders_qs
    ]

    # Unresolved /? markers (question signals, still pending)
    unresolved_questions_qs = (
        WritingMarkerOccurrence.objects
        .filter(
            piece__author=user,
            raw_name="?",
            status=WritingMarkerOccurrence.STATUS_PENDING,
        )
        .select_related("piece")
        .order_by("-created_at")[:20]
    )
    unresolved_questions = [
        {
            "id": str(m.id),
            "piece_id": str(m.piece_id),
            "piece_title": m.piece.title or "",
            "piece_slug": m.piece.slug or "",
            "label": m.label,
            "body": m.body,
            "created_at": m.created_at.isoformat(),
        }
        for m in unresolved_questions_qs
    ]

    return {
        "stale_drafts": stale_drafts,
        "overdue_reminders": overdue_reminders,
        "unresolved_questions": unresolved_questions,
        "stale_threshold_days": STALE_DRAFT_DAYS,
    }
