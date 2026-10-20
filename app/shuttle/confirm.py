# shuttle/confirm.py
#
# The Governed Verb Envelope's confirm half (ADR-0058 D2, D4, D9; SH-7b).
# Applies the person's yes to a held packet (shuttle.services.start_weave
# + hold_packet) in one transaction: ticked items, ideas and adjacencies
# are written to their real models; anything else rests as a Seed.
#
# Near-duplicate matches are re-verified here rather than trusted from
# the packet the client already has (OQ2 Headnote, 2026-10-18) — a
# merge_answers "merge" decision is honored by id, but a plain "found"
# or "near_duplicate" state from packet-build time is re-derived live
# against fundamentals.services.name_matching, so drift between hold
# and confirm (another weave landing a same-named thing in between)
# doesn't silently merge the wrong row or silently fork a duplicate.
#
# Building the Idea facets for a Stories Not Yet Told offer (which
# Ideas characterize a given find) is agent work (SH-8) the contract
# has no field for yet; IdeaTuples land here with no Ideas attached
# until that exists.
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone

from classifications.models import Tag
from commons.leaf_services import add_entry, close_leaf, open_leaf
from commons.models import CommonsItem
from commons.services import capture_item
from fundamentals.services.name_matching import MatchState, match_against_queryset
from initiatives.models import ActionRunStatus
from relations.models import Relationship, RelationshipType
from tapestry.models import Location, Place
from writing.models import Seed

from .contract.validate import validate_confirm_in, validate_result_out
from .models import IdeaTuple
from .services import ShuttleEnvelopeError, _get_pending_action_run_for


def confirm_weave(*, action_run_id: str, confirm_in: dict, author) -> dict:
    """Apply one confirm to a held packet, in one transaction. Returns the
    result_out dict. Only the weave's own initiator may confirm it."""
    validate_confirm_in(confirm_in)
    action_run = _get_pending_action_run_for(action_run_id=action_run_id, author=author)
    packet = (action_run.request_payload or {}).get("packet")
    if packet is None:
        raise ShuttleEnvelopeError(f"ActionRun {action_run_id} has no held packet")

    action_run.status = ActionRunStatus.RUNNING
    action_run.save(update_fields=["status", "updated_at"])

    try:
        with transaction.atomic():
            result = _apply_confirm(packet=packet, confirm_in=confirm_in, author=author)
        result["action_run_id"] = str(action_run.id)
        validate_result_out(result)
    except Exception as exc:
        action_run.status = ActionRunStatus.FAILED
        action_run.error_payload = {"error": str(exc), "type": exc.__class__.__name__}
        action_run.completed_at = timezone.now()
        action_run.save(update_fields=["status", "error_payload", "completed_at", "updated_at"])
        raise

    action_run.status = ActionRunStatus.SUCCEEDED
    action_run.result_payload = result
    action_run.completed_at = timezone.now()
    action_run.save(update_fields=["status", "result_payload", "completed_at", "updated_at"])
    return result


def _apply_confirm(*, packet: dict, confirm_in: dict, author) -> dict:
    ticked = set(confirm_in["ticked_item_ids"])
    stories_by_item = {s["item_id"]: s for s in confirm_in.get("stories", [])}
    merge_by_item = {m["item_id"]: m for m in confirm_in.get("merge_answers", [])}
    reworded_by_idea = {r["idea_id"]: r["wording"] for r in confirm_in.get("idea_rewordings", [])}

    written = []
    rested = []
    things_by_item_id = {}

    for item in packet["items"]:
        item_id = item["item_id"]
        if item_id not in ticked:
            rested.append(item_id)
            continue

        if item["kind"] == "thing":
            commons_item = _resolve_or_create_thing(item=item, merge_answer=merge_by_item.get(item_id), author=author)
            written.append({"item_id": item_id, "written_as": "commons.CommonsItem", "id": str(commons_item.id)})
            things_by_item_id[item_id] = commons_item
            continue

        # kind == "place": a place with no story has nothing to capture yet (D9).
        story = stories_by_item.get(item_id)
        if story is None:
            rested.append(item_id)
            continue

        place = _resolve_or_create_place(item=item, merge_answer=merge_by_item.get(item_id))
        written.append({"item_id": item_id, "written_as": "tapestry.Place", "id": str(place.id)})

        leaf = open_leaf(author=author, place=place, kind="text")
        entry = add_entry(
            leaf=leaf,
            kind="text",
            body_text=story["text"],
            music_link=story.get("music_link", ""),
        )
        close_leaf(leaf=leaf, library_only=False)
        written.append({"item_id": item_id, "written_as": "commons.LeafEntry", "id": str(entry.id)})

    for idea in packet.get("ideas", []):
        idea_id = idea["idea_id"]
        if idea_id not in ticked:
            continue
        wording = reworded_by_idea.get(idea_id, idea["wording"])
        tag = _create_idea_tag(wording=wording)
        written.append({"item_id": idea_id, "written_as": "classifications.Tag", "id": str(tag.id)})

    for adjacency in packet.get("adjacencies", []):
        adjacency_id = adjacency["adjacency_id"]
        if adjacency_id not in ticked:
            continue
        end_a, end_b = adjacency["ends"]
        if end_a not in things_by_item_id or end_b not in things_by_item_id:
            raise ShuttleEnvelopeError(
                f"Adjacency {adjacency_id} was ticked without both of its ends ticked."
            )
        relationship = _create_adjacency(
            source=things_by_item_id[end_a],
            target=things_by_item_id[end_b],
            reason=adjacency["reason"],
            author=author,
        )
        written.append({"item_id": adjacency_id, "written_as": "relations.Relationship", "id": str(relationship.id)})

    stories_not_yet_told = packet.get("stories_not_yet_told")
    if stories_not_yet_told and confirm_in.get("stories_not_yet_told_answer"):
        for offer in stories_not_yet_told["offers"]:
            idea_tuple = IdeaTuple.objects.create(
                label=offer["label"],
                source_offer_id=offer["id"],
                author=author,
            )
            written.append({"item_id": offer["id"], "written_as": "shuttle.IdeaTuple", "id": str(idea_tuple.id)})

    items_by_id = {item["item_id"]: item for item in packet["items"]}
    for item_id in rested:
        item = items_by_id[item_id]
        Seed.objects.create(
            author=author,
            body_text=f"{item['name']} ({item['locale']})",
            source="shuttle",
        )

    return {"version": "1.0", "written": written, "rested_as_seed": rested}


def _resolve_or_create_thing(*, item: dict, merge_answer: dict | None, author) -> CommonsItem:
    if merge_answer and merge_answer["decision"] == "merge":
        try:
            return CommonsItem.objects.get(pk=merge_answer["candidate_id"])
        except ObjectDoesNotExist as exc:
            raise ShuttleEnvelopeError(
                f"Merge target {merge_answer['candidate_id']} for {item['item_id']} no longer exists."
            ) from exc

    match = match_against_queryset(name=item["name"], queryset=CommonsItem.objects.all(), name_field="title")
    if match.state == MatchState.FOUND:
        return match.exact

    return capture_item(author, title=item["name"])


def _resolve_or_create_place(*, item: dict, merge_answer: dict | None) -> Place:
    if merge_answer and merge_answer["decision"] == "merge":
        try:
            return Place.objects.get(pk=merge_answer["candidate_id"])
        except ObjectDoesNotExist as exc:
            raise ShuttleEnvelopeError(
                f"Merge target {merge_answer['candidate_id']} for {item['item_id']} no longer exists."
            ) from exc

    match = match_against_queryset(name=item["name"], queryset=Place.objects.all(), name_field="name")
    if match.state == MatchState.FOUND:
        return match.exact

    return Place.objects.create(name=item["name"], location=Location.objects.create())


def _create_idea_tag(*, wording: str) -> Tag:
    # Same get_or_create(title__iexact=...) convention as writing.publish_service
    # — slugs auto-generate from title (BaseData), not set here.
    tag, _ = Tag.objects.get_or_create(title__iexact=wording, defaults={"title": wording, "is_idea": True})
    if not tag.is_idea:
        tag.is_idea = True
        tag.save(update_fields=["is_idea"])
    return tag


def _create_adjacency(*, source: CommonsItem, target: CommonsItem, reason: str, author) -> Relationship:
    relationship_type = RelationshipType.objects.get(slug="adjacent", domain=RelationshipType.DOMAIN_COMMONS)
    return Relationship.objects.create(
        source_content_type=_content_type(source),
        source_object_id=source.pk,
        target_content_type=_content_type(target),
        target_object_id=target.pk,
        relationship_type=relationship_type,
        notes=reason,
        created_by=author,
    )


def _content_type(obj):
    from django.contrib.contenttypes.models import ContentType

    return ContentType.objects.get_for_model(obj)
