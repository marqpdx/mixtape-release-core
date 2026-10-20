# commons/leaf_services.py
#
# Open/accumulate/close services for Leaf and LeafEntry (ADR-0049 D5, D6, D7),
# shared by the Commons composer (CM-7 Field Notes: Open -> Accumulate ->
# Close -> Place/Time/People -> Share or Keep Private, CM-7 to CM-11) and
# Shuttle (ADR-0058 D4: a story is a Leaf and LeafEntry, closed on approval;
# a run at one place is a Commons Thread).

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .models import Leaf, LeafEntry


class LeafServiceError(Exception):
    pass


def detect_music_provider(music_link: str) -> str:
    """Spotify first (ADR-0058 D4); anything else is held as a link with
    no provider tag rather than guessed at."""
    if not music_link:
        return ""
    if "open.spotify.com" in music_link or "spotify.link" in music_link:
        return LeafEntry.MUSIC_PROVIDER_SPOTIFY
    return ""


@transaction.atomic
def open_leaf(*, author, place=None, kind="text", visibility="public"):
    """Start an open Leaf. Add content with add_entry; finish with close_leaf."""
    return Leaf.objects.create(
        author=author,
        place=place,
        kind=kind,
        visibility=visibility,
        state=Leaf.STATE_OPEN,
    )


@transaction.atomic
def add_entry(
    *,
    leaf,
    kind,
    body_text="",
    body_json=None,
    image_file=None,
    audio_file=None,
    shared=True,
    music_link="",
):
    """
    Append the next-ordered LeafEntry (D6). Only open Leaves accept entries —
    a closed Leaf's entries are final, including for shared=False trims (D7).

    `music_link` is optional media on the entry (D4, SH-4); its provider is
    detected automatically (Spotify first; a generic field for later providers).
    """
    if leaf.state != Leaf.STATE_OPEN:
        raise LeafServiceError("Cannot add an entry to a closed Leaf.")

    next_position = (
        leaf.entries.aggregate(max_position=Max("position"))["max_position"] or 0
    ) + 1

    return LeafEntry.objects.create(
        leaf=leaf,
        kind=kind,
        position=next_position,
        body_text=body_text,
        body_json=body_json or None,
        image_file=image_file,
        audio_file=audio_file,
        shared=shared,
        music_link=music_link,
        music_provider=detect_music_provider(music_link),
    )


@transaction.atomic
def close_leaf(*, leaf, library_only=False, occurred_at=None):
    """
    Close an open Leaf (D5). A Leaf shared to Commons (library_only=False)
    must already have its Place (OQ-5, enforced here per the model's own
    docstring) -- Shuttle sets it at open_leaf time; the Commons composer
    sets it at its Place/Time/People screen (CM-9), before Close (CM-10/11).

    Idempotent: closing an already-closed Leaf returns it unchanged.
    """
    if leaf.state == Leaf.STATE_CLOSED:
        return leaf

    if not library_only and leaf.place_id is None:
        raise LeafServiceError(
            "A Leaf shared to Commons needs a Place before it can close."
        )

    leaf.library_only = library_only
    leaf.state = Leaf.STATE_CLOSED
    if occurred_at is not None:
        leaf.occurred_at = occurred_at
    if not library_only and leaf.published_at is None:
        leaf.published_at = timezone.now()

    leaf.save(update_fields=["library_only", "state", "occurred_at", "published_at", "updated_at"])
    return leaf
