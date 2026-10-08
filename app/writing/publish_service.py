# writing/publish_service.py
"""
Publish-and-place service for WritingPiece.

Extracted from WritingPiecePublishAndPlaceView.post() (QC-2).
Handles the full flow: field edits → working-copy merge → publish/schedule
→ artifact (WritingVersion) creation → placement creation.
"""
import logging

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import dateparse, timezone

from groups.services.permissions import PermissionService
from publishing.models import ContentPlacement, PublicationGroup

from .models import WritingPiece, WritingVersion, WorkingDocument, is_provisional_slug

logger = logging.getLogger(__name__)


def _coerce_bool(v, default=False):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("1", "true", "yes", "y", "on")
    return default


def ensure_published_feed_placement(piece, user, target, *, visibility="public"):
    """Place an already-published piece without creating another release version."""
    if piece.status != "published":
        raise ValidationError("Only published pieces can be placed in a feed.")

    source_type = ContentType.objects.get_for_model(WritingPiece)
    target_type = ContentType.objects.get_for_model(target)
    existing = ContentPlacement.objects.filter(
        source_content_type=source_type,
        source_object_id=piece.id,
        target_content_type=target_type,
        target_object_id=target.pk,
        channel="feed",
    ).first()
    if existing:
        return existing

    version = piece.versions.filter(kind="release").order_by("-sequence_no").first()
    if version is None:
        version = piece.create_version(content_changed=True)
        piece.current_version_no = version.sequence_no
        piece.save(update_fields=["current_version_no", "updated_at"])

    publication_group = PublicationGroup.objects.create(
        created_by=user,
        source_content_type=source_type,
        source_object_id=piece.id,
    )
    return ContentPlacement.objects.create(
        publication_group=publication_group,
        placed_by=user,
        source_content_type=source_type,
        source_object_id=piece.id,
        target_content_type=target_type,
        target_object_id=target.pk,
        channel="feed",
        visibility=visibility,
        follow_updates=False,
        locked_artifact_content_type=ContentType.objects.get_for_model(version),
        locked_artifact_object_id=version.pk,
    )


@transaction.atomic
def publish_and_place(piece: WritingPiece, user, data: dict) -> dict:
    """
    Execute the full publish-and-place flow for a WritingPiece.

    Args:
        piece: A WritingPiece instance (must already have permissions verified by caller).
        user: The authenticated user performing the action.
        data: Deserialized request payload (see WritingPiecePublishAndPlaceView docstring).

    Returns:
        {
            "piece": WritingPiece,
            "placements_created": int,
            "placements": list[ContentPlacement],
            "pub_group": PublicationGroup | None,
            "scheduled": bool,
        }

    Raises:
        ValidationError: for user-correctable errors (missing title, bad date, no destinations).
    """
    destinations = data.get("destinations", {}) or {}
    placement_defaults = data.get("placement_options", {}) or {}
    group_overrides = data.get("group_overrides", {}) or {}
    audience = data.get("audience")

    has_destinations = any([
        destinations.get("personal"),
        destinations.get("lantern"),
        destinations.get("groups"),
        destinations.get("shelves"),
    ])
    if not has_destinations and audience != "just_me":
        raise ValidationError("At least one destination must be selected.")

    # Parse scheduled_for
    scheduled_for = None
    if data.get("scheduled_for"):
        scheduled_for = dateparse.parse_datetime(data["scheduled_for"])
        if not scheduled_for:
            raise ValidationError("scheduled_for must be ISO8601 datetime.")

    # default follow_updates (v1: locked by default)
    default_follow_updates = _coerce_bool(placement_defaults.get("follow_updates"), False)

    # Apply optional field edits to piece
    editable_fields = {}
    for fld in ("title", "excerpt", "canonical_url", "writing_kind", "body_json", "addressed_to"):
        if fld in data:
            editable_fields[fld] = data[fld]

    if editable_fields:
        if editable_fields.get("title") in (None, ""):
            editable_fields["title"] = "Untitled"
        if "addressed_to" in editable_fields and not editable_fields["addressed_to"]:
            editable_fields.pop("addressed_to")
        piece.__dict__.update({k: v for k, v in editable_fields.items() if v is not None})
        if "title" in editable_fields and is_provisional_slug(piece.slug):
            piece.slug = None
        piece.save(update_fields=list(editable_fields.keys()) + ["updated_at"])

    # Merge working copy if one exists
    wc = WorkingDocument.objects.filter(piece=piece, user=user).first()
    if wc:
        wc.apply_to_piece(piece)

    # Tags
    if hasattr(piece, "tags") and isinstance(data.get("tags"), (list, tuple)):
        piece.tags.set(data["tags"])

    # addressed_to default
    if not piece.addressed_to:
        if audience == "just_me":
            piece.addressed_to = WritingPiece.AddressedTo.SELF
        elif audience == "readers":
            piece.addressed_to = WritingPiece.AddressedTo.PUBLIC

    # Publish or schedule
    if scheduled_for:
        if not (piece.title or "").strip():
            raise ValidationError("Please add a title before scheduling.")
        piece.status = "scheduled"
        piece.scheduled_for = scheduled_for
        piece.save(update_fields=["status", "scheduled_for", "slug", "updated_at", "addressed_to"])
    else:
        if not (piece.title or "").strip():
            raise ValidationError("Please add a title before publishing.")
        piece.status = "published"
        piece.published_at = timezone.now()
        piece.save(update_fields=["status", "published_at", "slug", "updated_at", "addressed_to"])

    # Create immutable artifact (WritingVersion)
    next_sequence_no = (
        WritingVersion.objects.filter(writing_piece=piece)
        .aggregate(Max("sequence_no"))
        .get("sequence_no__max") or 0
    ) + 1
    writing_version = WritingVersion.objects.create(
        writing_piece=piece,
        sequence_no=next_sequence_no,
        version_label=str(next_sequence_no),
        body_json=piece.body_json,
        title=piece.title,
        excerpt=piece.excerpt,
        kind="release",
        created_by=user,
    )
    piece.current_version_no = next_sequence_no
    piece.save(update_fields=["current_version_no", "updated_at"])

    # Generate/refresh synopsis (non-blocking — never raises)
    if piece.status == "published":
        try:
            from writing.synopsis_service import SynopsisGenerationService
            SynopsisGenerationService.generate_for_piece(piece)
        except Exception:
            logger.exception("Synopsis generation failed for piece %s — skipping", piece.id)
        def enqueue_synopsis():
            try:
                from writing.tasks import enqueue_writing_piece_synopsis_task
                enqueue_writing_piece_synopsis_task.delay(str(piece.id))
            except Exception:
                logger.exception("AI synopsis enqueue failed for piece %s — skipping", piece.id)

        transaction.on_commit(enqueue_synopsis)

    # --- Placement creation ---
    ct_piece = ContentType.objects.get_for_model(WritingPiece)
    pub_group = None
    placements_created = 0
    placements = []
    excerpt_override = data.get("summary") or piece.excerpt or data.get("excerpt")

    def ensure_publication_group():
        nonlocal pub_group
        if pub_group is None:
            pub_group = PublicationGroup.objects.create(
                created_by=user,
                source_content_type=ct_piece,
                source_object_id=piece.id,
                note=data.get("publish_note", ""),
            )
        return pub_group

    def build_placement_kwargs(base_opts, override_opts=None):
        opts = dict(base_opts or {})
        opts.update(override_opts or {})
        follow_updates = _coerce_bool(opts.get("follow_updates"), default_follow_updates)
        is_excerpt = _coerce_bool(opts.get("is_excerpt"), False)
        visibility = "scheduled" if piece.status == "scheduled" else opts.get("visibility", "public")
        locked_artifact_ct = None
        locked_artifact_id = None
        if not follow_updates:
            locked_artifact_ct = ContentType.objects.get_for_model(writing_version.__class__)
            locked_artifact_id = writing_version.id
        return {
            "follow_updates": follow_updates,
            "locked_artifact_content_type": locked_artifact_ct,
            "locked_artifact_object_id": locked_artifact_id,
            "visibility": visibility,
            "is_excerpt": is_excerpt,
            "fragment_selector": opts.get("fragment_selector"),
            "overrides": opts.get("overrides", {}),
        }

    def apply_excerpt(kwargs):
        if excerpt_override:
            kwargs["overrides"]["excerpt"] = excerpt_override

    # Personal feed
    if destinations.get("personal"):
        ct_user = ContentType.objects.get_for_model(user.__class__)
        kwargs = build_placement_kwargs(placement_defaults)
        apply_excerpt(kwargs)
        placement, created = ContentPlacement.objects.update_or_create(
            source_content_type=ct_piece,
            source_object_id=piece.id,
            target_content_type=ct_user,
            target_object_id=user.id,
            channel="feed",
            defaults={"publication_group": ensure_publication_group(), "placed_by": user, **kwargs},
        )
        if created:
            placements_created += 1
        placements.append(placement)

    # Groups
    group_idents = destinations.get("groups") or []
    if group_idents:
        from groups.models import Group
        ct_group = ContentType.objects.get_for_model(Group)
        for ident in group_idents:
            grp = None
            try:
                grp = Group.objects.get(slug=ident)
            except Group.DoesNotExist:
                try:
                    grp = Group.objects.get(id=ident)
                except Group.DoesNotExist:
                    continue
            if not PermissionService.can_user_perform_action(user, "publish_writing", group_slug=grp.slug):
                continue
            g_override = group_overrides.get(str(ident)) or group_overrides.get(str(grp.id)) or {}
            kwargs = build_placement_kwargs(placement_defaults, g_override)
            apply_excerpt(kwargs)
            placement, created = ContentPlacement.objects.update_or_create(
                source_content_type=ct_piece,
                source_object_id=piece.id,
                target_content_type=ct_group,
                target_object_id=grp.id,
                channel="feed",
                defaults={"publication_group": ensure_publication_group(), "placed_by": user, **kwargs},
            )
            if created:
                placements_created += 1
            placements.append(placement)

    # Lantern (Newsletter)
    if destinations.get("lantern"):
        ct_user = ContentType.objects.get_for_model(user.__class__)
        kwargs = build_placement_kwargs(placement_defaults)
        overrides = kwargs.get("overrides", {}).copy()
        if not overrides.get("lantern_subject"):
            overrides["lantern_subject"] = f"New from {user.get_full_name() or user.username}: {piece.title}"
        kwargs["overrides"] = overrides
        apply_excerpt(kwargs)
        placement, created = ContentPlacement.objects.update_or_create(
            source_content_type=ct_piece,
            source_object_id=piece.id,
            target_content_type=ct_user,
            target_object_id=user.id,
            channel="lantern",
            defaults={"publication_group": ensure_publication_group(), "placed_by": user, **kwargs},
        )
        if created:
            placements_created += 1
        placements.append(placement)

    # Shelves (Collection placements)
    shelf_ids = destinations.get("shelves") or []
    if shelf_ids:
        from curation.models import Collection
        ct_collection = ContentType.objects.get_for_model(Collection)
        for shelf in Collection.objects.filter(id__in=shelf_ids):
            next_order = (
                ContentPlacement.objects.filter(
                    target_content_type=ct_collection,
                    target_object_id=shelf.id,
                    channel="shelf",
                ).aggregate(Max("order_index")).get("order_index__max") or 0
            ) + 1
            kwargs = build_placement_kwargs(placement_defaults)
            if piece.status != "scheduled":
                kwargs["visibility"] = shelf.visibility
            apply_excerpt(kwargs)
            placement, created = ContentPlacement.objects.update_or_create(
                source_content_type=ct_piece,
                source_object_id=piece.id,
                target_content_type=ct_collection,
                target_object_id=shelf.id,
                channel="shelf",
                defaults={
                    "publication_group": ensure_publication_group(),
                    "placed_by": user,
                    "order_index": next_order,
                    **kwargs,
                },
            )
            if created:
                placements_created += 1
            placements.append(placement)

    return {
        "piece": piece,
        "placements_created": placements_created,
        "placements": placements,
        "pub_group": pub_group,
        "scheduled": bool(scheduled_for),
    }
