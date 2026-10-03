# folio/shapes.py
#
# Folio Notes PoC — the single seam for Shape vocabulary
# (puddlejump/decisions/folio/folio-notes-poc-mobile-handoff.md, correction 1).
#
# Shapes are stored on FolioNote as plain strings. Anything that needs to
# validate or branch on a Shape value goes through this module, so that when
# Shape validation moves to the Shapes Library (catalyst ShapeLibrary /
# puddlejump/reference/shapes/*.yaml) and becomes Contour-parameterized,
# there is one place to redirect rather than many.

from django.db import models


class Shape(models.TextChoices):
    # The initial fiction Contour's Shapes (build plan §3.4). Not a rigid
    # content-type system — broad organizational affordances.
    CHARACTER = "character", "Character"
    SCENE = "scene", "Scene"
    PLOT = "plot", "Plot"
    PLACE = "place", "Place"
    WORLD = "world", "World"
    META = "meta", "Meta"
    UNPLACED = "unplaced", "Unplaced"


def effective_shape(suggested_shape: str, confirmed_shape: str) -> str:
    """Human confirmation wins over model suggestion; absent both, Unplaced
    (build plan §4.5 — Unplaced is curated provisionality, not an error)."""
    return confirmed_shape or suggested_shape or Shape.UNPLACED


def allowed_shapes() -> list[str]:
    """The vocabulary sent to tending (Switchboard → Inkwell folio_note_tend),
    so Inkwell never hard-codes a Contour's Shapes."""
    return list(Shape.values)


def coerce_shape(value) -> str:
    """Validate a model-suggested Shape; anything unrecognized is Unplaced."""
    return value if value in Shape.values else Shape.UNPLACED
