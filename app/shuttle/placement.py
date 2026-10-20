# shuttle/placement.py
#
# SH-8: the Shuttle verb's placement half. Deterministic resolution and
# assembly over the Contour Sightings that shuttle_weave_interpret (SH-11)
# returned — no model calls (CTO, 2026-10-20 reframe). Anything needing
# judgement already happened in the Sightings; this module only matches
# names against live rows (SH-1) and shapes the result into an SH-7a
# packet, held via shuttle.services.hold_packet.
#
# Explicit scope boundary: the Sighting contract (shuttle/interpretation/
# contract.py) has no field for externally-sourced finds — Ariadne-style
# linking to material the person never mentioned. packet_out's optional
# stories_not_yet_told is therefore always omitted here; nothing upstream
# produces it yet. If/when that search exists, it plugs in here.
from classifications.models import Tag
from commons.models import CommonsItem
from fundamentals.services.name_matching import MatchState, match_against_queryset
from tapestry.models import Place

from .interpretation.lifecycle import owned_parent
from .services import hold_packet

# Callables, not pre-built querysets — a queryset built once at import time
# caches its results on first iteration and never re-queries the DB again
# for the life of the process.
_RESOLUTION_TARGETS = {
    "shuttle.thing": (lambda: CommonsItem.objects.all(), "title"),
    "shuttle.place": (lambda: Place.objects.all(), "name"),
    "shuttle.idea": (lambda: Tag.objects.filter(is_idea=True), "title"),
}


class PlacementError(Exception):
    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(code)


def _queryset_for(shape_id):
    build_queryset, name_field = _RESOLUTION_TARGETS[shape_id]
    return build_queryset(), name_field


def _sighting_name(sighting):
    if sighting["shape_id"] == "shuttle.idea":
        return sighting["wording"]
    return sighting["proposed_name"] or sighting["name_as_said"]


def _display_name(obj):
    return getattr(obj, "title", None) or getattr(obj, "name", None) or str(obj)


def _resolution_entry(match):
    if match.state == MatchState.FOUND:
        return {"status": "found", "candidates": [
            {"id": str(match.exact.pk), "name": _display_name(match.exact), "score": 1.0}]}
    if match.state == MatchState.NEAR_DUPLICATE:
        return {"status": "near_duplicate", "candidates": [
            {"id": str(c.object.pk), "name": c.name, "score": round(c.score / 100, 2)}
            for c in match.candidates]}
    return {"status": "new", "candidates": []}


def resolve_sightings(findings: dict) -> dict:
    """Populate resolution.candidates for every still-unresolved thing/place/
    idea Sighting via live SH-1 matching. The name to match is already in
    the Sighting; no model call is made."""
    sightings_by_id = {s["sighting_id"]: s for s in findings["sightings"]}
    resolution = dict(findings.get("resolution") or {})
    for sighting_id, entry in resolution.items():
        if entry.get("status") != "unresolved":
            continue
        sighting = sightings_by_id[sighting_id]
        queryset, name_field = _queryset_for(sighting["shape_id"])
        match = match_against_queryset(name=_sighting_name(sighting), queryset=queryset, name_field=name_field)
        resolution[sighting_id] = _resolution_entry(match)
    return {**findings, "resolution": resolution}


def _item_match_state(entry):
    return {"found": "found", "near_duplicate": "near_duplicate", "new": "new"}[entry["status"]]


def _place_locale(sighting):
    return sighting.get("address_as_said") or sighting["proposed_name"] or sighting["name_as_said"]


def _thing_locale(sighting, sightings_by_id):
    place_ids = sighting.get("place_ids") or []
    if not place_ids:
        return ""
    place_sighting = sightings_by_id.get(place_ids[0])
    if place_sighting is None:
        return ""
    return place_sighting["proposed_name"] or place_sighting["name_as_said"]


def assemble_packet(findings: dict) -> dict:
    """Shape resolved Sightings into an SH-7a packet_out dict (without
    version/action_run_id — hold_packet fills those in)."""
    sightings_by_id = {s["sighting_id"]: s for s in findings["sightings"]}
    resolution = findings.get("resolution") or {}
    weave = next(s for s in findings["sightings"] if s["shape_id"] == "shuttle.weave")

    # A story's subject may be a thing or a Place (schema allows both), but a
    # story's real home is always a Place (Leaf.place) — resolve a thing
    # subject through its own place_ids rather than dropping the story.
    story_by_place_item_id = {}
    for story in (s for s in findings["sightings"] if s["shape_id"] == "shuttle.story"):
        for subject_id in story["subject_ids"]:
            subject = sightings_by_id[subject_id]
            place_item_ids = ([subject_id] if subject["shape_id"] == "shuttle.place"
                else subject.get("place_ids") or [])
            for place_item_id in place_item_ids:
                story_by_place_item_id.setdefault(place_item_id, story)

    items = []
    for sighting in findings["sightings"]:
        shape_id = sighting["shape_id"]
        if shape_id not in ("shuttle.thing", "shuttle.place"):
            continue
        entry = resolution.get(sighting["sighting_id"], {"status": "new", "candidates": []})
        item = {
            "item_id": sighting["sighting_id"],
            "kind": "thing" if shape_id == "shuttle.thing" else "place",
            "name": sighting["proposed_name"] or sighting["name_as_said"],
            "locale": _place_locale(sighting) if shape_id == "shuttle.place"
                else _thing_locale(sighting, sightings_by_id),
            "match_state": _item_match_state(entry),
        }
        if entry["status"] == "near_duplicate" and entry["candidates"]:
            item["candidate"] = entry["candidates"][0]
        items.append(item)

    ideas = []
    for sighting in findings["sightings"]:
        if sighting["shape_id"] != "shuttle.idea":
            continue
        entry = resolution.get(sighting["sighting_id"], {"status": "new", "candidates": []})
        ideas.append({
            "idea_id": sighting["sighting_id"],
            "wording": sighting["wording"],
            "closest_existing": entry["candidates"],
        })

    adjacencies = [
        {"adjacency_id": sighting["sighting_id"], "ends": sighting["ends"], "reason": sighting["reason"]}
        for sighting in findings["sightings"] if sighting["shape_id"] == "shuttle.adjacency"
    ]

    story_prompts = []
    for item in items:
        if item["kind"] != "place":
            continue
        prompt = {"item_id": item["item_id"], "prompt": "What happened the night you were there?"}
        story = story_by_place_item_id.get(item["item_id"])
        if story is not None:
            known_story = {"text": story["text"]}
            prompt["known_story"] = known_story
        story_prompts.append(prompt)

    return {
        "anchor": {
            "headline": f"Packet: {weave['reading']} · {len(items)} places/things · "
                        f"{len(ideas)} ideas · {len(adjacencies)} adjacencies",
            "counts": {
                "places": sum(1 for i in items if i["kind"] == "place"),
                "ideas": len(ideas),
                "adjacencies": len(adjacencies),
            },
        },
        "items": items,
        "ideas": ideas,
        "adjacencies": adjacencies,
        "story_prompts": story_prompts,
    }


def build_packet(*, action_run_id: str, author) -> dict:
    """SH-8's placement step: resolve the weave's findings against live
    rows, assemble an SH-7a packet, and hold it. Raises PlacementError if
    the weave has no succeeded interpretation to build from."""
    parent = owned_parent(action_run_id, author, lock=True)
    state = parent.request_payload.get("interpretation") or {}
    if state.get("status") != "succeeded" or not state.get("findings"):
        raise PlacementError("interpretation_not_ready", 409)

    resolved = resolve_sightings(state["findings"])
    state["findings"] = resolved
    parent.request_payload = {**parent.request_payload, "interpretation": state}
    parent.save(update_fields=["request_payload", "updated_at"])

    packet = assemble_packet(resolved)
    return hold_packet(action_run_id=action_run_id, packet=packet, author=author)
