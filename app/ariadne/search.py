"""
Ariadne — P8: hybrid search and saved searches as Named Lenses
(build spec §19.1, scoped down from Inquiry Runs to just the search
primitive -- §19.2's full Inquiry Run workflow is P9, not this).

Hybrid search combines:
  - lexical: exact/phrase match via Passage.text icontains (§6's postings
    aren't built as a separate index; this reuses the same approach P6's
    packet assembly already uses)
  - vector: nearest neighbours from Ariadne's Qdrant collection (P8 above)
  - concept expansion: a query matching a Concept's preferred_label or an
    alias also searches by that Concept's other aliases (§19.1 -- "and its
    Likeness members" is skipped, since Likeness isn't built)

Each hit says which method(s) found it, per §19.1's "each hit says which
of the three found it."
"""

from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .embedding import embed_texts, ensure_collection, get_qdrant_client
from .models import Concept, Lens, LensVersion, Passage

DEFAULT_LIMIT = 20


def _expand_via_concepts(query_text: str) -> list[str]:
    """§19.1: a query that matches a Concept also searches its aliases."""
    terms = set()
    concepts = Concept.objects.filter(preferred_label__iexact=query_text) | Concept.objects.filter(
        aliases__alias__iexact=query_text
    )
    for concept in concepts.distinct().prefetch_related("aliases"):
        terms.add(concept.preferred_label)
        terms.update(alias.alias for alias in concept.aliases.all())
    terms.discard(query_text)
    return sorted(terms)


def hybrid_search(query_text: str, limit: int = DEFAULT_LIMIT) -> list[dict]:
    expansion_terms = _expand_via_concepts(query_text)
    lexical_terms = [query_text, *expansion_terms]

    results: dict[str, dict] = {}

    lexical_matches = Passage.objects.none()
    for term in lexical_terms:
        lexical_matches = lexical_matches | Passage.objects.filter(text__icontains=term)
    for passage in lexical_matches.distinct().select_related("revision__document")[:limit]:
        results[str(passage.id)] = _result_entry(passage, found_by=["lexical"], score=None)

    try:
        ensure_collection()
        vector = embed_texts([query_text])[0]
        hits = get_qdrant_client().query_points(
            collection_name=settings.ARIADNE_QDRANT_COLLECTION, query=vector, limit=limit
        ).points
    except Exception:
        # P8 note: a Qdrant outage degrades to lexical-only results rather
        # than failing the whole search -- vector search is additive here.
        hits = []

    if hits:
        passage_ids = [hit.id for hit in hits]
        passages_by_id = {
            str(p.id): p
            for p in Passage.objects.filter(id__in=passage_ids).select_related("revision__document")
        }
        for hit in hits:
            passage = passages_by_id.get(str(hit.id))
            if passage is None:
                continue
            key = str(passage.id)
            if key in results:
                results[key]["found_by"].append("vector")
                results[key]["vector_score"] = hit.score
            else:
                results[key] = _result_entry(passage, found_by=["vector"], score=hit.score)

    if expansion_terms:
        for entry in results.values():
            entry["concept_expansion_terms"] = expansion_terms

    # Found twice during P8 verification against the live corpus, for a
    # query common enough to have many literal hits ("catalyst"):
    # (1) sorting by vector_score alone, treating "no score" as worst,
    #     silently crowded every exact lexical match out of the results,
    #     even for a query that matched a document's own title;
    # (2) giving lexical matches first claim on the result slots just as
    #     badly crowded out every semantic neighbour instead -- once
    #     there were >= limit literal hits, no vector hit ever surfaced,
    #     which defeats the actual point of a *hybrid* search.
    # Fix: hits found by both methods always surface; the remaining slots
    # split evenly between lexical-only and vector-only, so neither
    # method's signal can fully crowd out the other's, with any shortfall
    # on one side handed to the other.
    both = [r for r in results.values() if len(r["found_by"]) == 2]
    lexical_only = [r for r in results.values() if r["found_by"] == ["lexical"]]
    vector_only = sorted(
        (r for r in results.values() if r["found_by"] == ["vector"]),
        key=lambda r: -(r.get("vector_score") or 0),
    )

    remaining = max(limit - len(both), 0)
    lexical_share, vector_share = remaining // 2, remaining - remaining // 2
    taken_lexical = lexical_only[:lexical_share]
    taken_vector = vector_only[:vector_share]
    shortfall = remaining - len(taken_lexical) - len(taken_vector)
    if shortfall > 0:
        taken_lexical += lexical_only[len(taken_lexical) : len(taken_lexical) + shortfall]
        shortfall = remaining - len(taken_lexical) - len(taken_vector)
    if shortfall > 0:
        taken_vector += vector_only[len(taken_vector) : len(taken_vector) + shortfall]

    return (both + taken_lexical + taken_vector)[:limit]


def _result_entry(passage: Passage, *, found_by: list[str], score: float | None) -> dict:
    return {
        "passage_id": str(passage.id),
        "document_title": passage.revision.document.title,
        "document_uri": passage.revision.document.uri,
        "source_key": passage.revision.document.source_key,
        "excerpt": passage.text[:300],
        "found_by": found_by,
        "vector_score": score,
    }


def save_search_as_lens(*, name: str, query_text: str, owner) -> LensVersion:
    """A saved search is a Named Lens (§19.1) -- no new object, the
    existing Lens/LensVersion mechanics (P5) carry it. config.kind
    distinguishes a search Lens from a Discovery ranking Lens."""
    with transaction.atomic():
        lens, _created = Lens.objects.get_or_create(name=name, defaults={"owner": owner})
        last_version = lens.versions.order_by("-version").first()
        next_version = (last_version.version + 1) if last_version else 1
        config = {"kind": "search", "query": query_text}
        lens_version = LensVersion.objects.create(
            lens=lens,
            version=next_version,
            config=config,
            config_hash=f"search:{query_text}:{timezone.now().timestamp()}",
        )
        lens.active_version = lens_version
        lens.save(update_fields=["active_version"])
    return lens_version


def list_saved_searches():
    return Lens.objects.filter(active_version__config__kind="search").select_related("active_version")


def run_saved_search(lens: Lens, limit: int = DEFAULT_LIMIT) -> list[dict]:
    query_text = lens.active_version.config["query"]
    return hybrid_search(query_text, limit=limit)
