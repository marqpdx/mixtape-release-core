from django.contrib.contenttypes.models import ContentType

from classifications.models import Category, Tag, ClassificationUsage


def compute_craft_readiness(writing_piece) -> dict:
    """
    Computes readiness state for five Atelier dimensions.
    Returns a dict; states are "untouched" | "partial" | "confirmed" | "deferred".
    """
    piece_ct = ContentType.objects.get_for_model(writing_piece)
    piece_id = str(writing_piece.pk)

    tag_ct = ContentType.objects.get_for_model(Tag)
    cat_ct = ContentType.objects.get_for_model(Category)

    tag_count = ClassificationUsage.objects.filter(
        classification_client_content_type=piece_ct,
        classification_client_object_id=piece_id,
        classification_content_type=tag_ct,
    ).count()

    cat_count = ClassificationUsage.objects.filter(
        classification_client_content_type=piece_ct,
        classification_client_object_id=piece_id,
        classification_content_type=cat_ct,
    ).count()

    synopsis = getattr(writing_piece, "synopsis", None)

    tags = "confirmed" if tag_count >= 1 else "untouched"
    category = "confirmed" if cat_count >= 1 else "untouched"
    series = "confirmed" if writing_piece.series_id else "untouched"
    relations = "deferred"

    if synopsis is None:
        summaries = "untouched"
    else:
        confirmed = any([
            synopsis.public_synopsis_confirmed,
            synopsis.linkedin_synopsis_confirmed,
            synopsis.internal_abstract_confirmed,
        ])
        has_text = any([
            bool(synopsis.description),
            bool(synopsis.linkedin_copy),
            bool(synopsis.internal_abstract),
        ])
        if confirmed:
            summaries = "confirmed"
        elif has_text:
            summaries = "partial"
        else:
            summaries = "untouched"

    active = [tags, category, summaries, series]
    if all(s == "confirmed" for s in active):
        overall = "confirmed"
    elif any(s in ("confirmed", "partial") for s in active):
        overall = "partial"
    else:
        overall = "untouched"

    return {
        "tags": tags,
        "category": category,
        "summaries": summaries,
        "series": series,
        "relations": relations,
        "overall": overall,
    }


def get_readiness_warnings(writing_piece) -> list[str]:
    """
    Returns human-readable warning strings for untouched readiness dimensions.
    Used at publish time (warn-not-block).
    """
    readiness = compute_craft_readiness(writing_piece)
    warnings = []

    if readiness["tags"] == "untouched":
        warnings.append("No tags have been added to this piece.")
    if readiness["category"] == "untouched":
        warnings.append("No category has been set for this piece.")
    if readiness["summaries"] == "untouched":
        warnings.append("No summaries have been written for this piece.")
    if readiness["series"] == "untouched":
        warnings.append("This piece is not part of any series.")

    return warnings
