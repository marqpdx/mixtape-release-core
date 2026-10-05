# storyboard/grammars.py
#
# A grammar is plain code, not a Contour shape and not a database row.
# See decisions/folio/folio-storyboard-review.md §6 (puddlejump) for the
# full reasoning: a Contour shape describes content (recipe/course/product
# fields); a grammar describes structure (which levels exist, what nests
# under what, what a level may reference). Revisit only if a second real
# grammar consumer creates genuine non-engineer-authoring pressure -- not
# before (named uplift trigger, review §6).

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Grammar:
    """
    Declares the shape of one Storyboard arrangement: which levels exist,
    what each level may be parented under, what a level's StoryboardItem
    may reference, and which Participation kinds (Phase 7) it offers.
    """

    levels: list[str]
    # level -> "app_label.ModelName" for levels whose StoryboardItem.reference
    # points at canonical content; a level absent from this dict (e.g. a
    # purely structural "part") never carries a reference.
    level_references: dict[str, str]
    # level -> list of allowed parent levels; None means "may be a root item".
    allowed_parents: dict[str, list[str | None]]
    participation_kinds: list[str] = field(default_factory=list)


FICTION_V1 = Grammar(
    levels=["part", "chapter", "scene"],
    level_references={"scene": "writing.WritingPiece"},
    allowed_parents={
        "part": [None],
        "chapter": ["part", None],
        "scene": ["chapter"],
    },
    # Character satellites are Phase 7 -- not needed for the Phase 5 spine.
    participation_kinds=[],
)

GRAMMARS: dict[str, Grammar] = {
    "fiction_v1": FICTION_V1,
}


def get_grammar(key: str) -> Grammar:
    try:
        return GRAMMARS[key]
    except KeyError:
        raise ValueError(f"Unknown storyboard grammar: {key!r}")
