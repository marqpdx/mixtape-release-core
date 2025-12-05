# ai/ultils/filters.py

from django.db.models import Q

from inkwell.models import DeclinedAsset, IngestedFile, SuggestedAsset


def get_excluded_source_ids(sources: list[str]) -> set:
    source_filter = Q()
    for source in sources:
        source_filter |= Q(suggested_asset__source=source)

    declined_ids = DeclinedAsset.objects.filter(source_filter).values_list(
        "suggested_asset__source_id", flat=True
    )

    suggested_ids = SuggestedAsset.objects.filter(
        source__in=sources
    ).values_list("source_id", flat=True)

    # Include ingested file hashes for matching source_ids
    ingested_ids = IngestedFile.objects.values_list("filehash", flat=True)

    return set(declined_ids).union(suggested_ids).union(ingested_ids)

