"""
Ariadne — P6 curation workbench services (build spec §9 4A-4D, §10).

Deterministic only, per §11 ("use deterministic operations wherever
possible"): no model calls here. §9's 4E (Interpret) and 4F's assertion
curation are NOT implemented yet -- they need a model task registry (§11)
that hasn't been designed, and are out of scope for this pass. What's here
covers 4A (candidates already ranked by the Discovery Run command), 4B
(record a disposition), 4C (assemble a packet from exact mentions only --
vector neighbours are P8, not built yet) and 4D (the packet itself, for
review).
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .models import (
    Concept,
    CurationDecision,
    DiscoveryRun,
    EvidencePacket,
    Passage,
    RunCandidate,
)

MAX_PACKET_PASSAGES = 25


def record_decision(
    *, run: DiscoveryRun, candidate: RunCandidate, action: str, reason: str, actor
) -> CurationDecision:
    """§9 4B: record a disposition immediately. 'accept' promotes the
    candidate's phrase to a real Concept (get-or-create by preferred_label)
    so P6a's lookup has something real to find -- nothing upstream of this
    creates Concept rows from a Discovery Run's output otherwise."""

    with transaction.atomic():
        previous = (
            CurationDecision.objects.filter(run=run, candidate_key=candidate.concept_or_phrase_key)
            .order_by("-created_at")
            .first()
        )
        decision = CurationDecision.objects.create(
            run=run,
            candidate_key=candidate.concept_or_phrase_key,
            action=action,
            actor=actor,
            reason=reason,
            supersedes=previous,
        )

        candidate.disposition = action
        candidate.disposition_reason = reason
        candidate.disposition_at = timezone.now()

        if action == CurationDecision.Action.ACCEPT:
            concept, _created = Concept.objects.get_or_create(
                preferred_label=candidate.concept_or_phrase_key,
                defaults={"status": Concept.Status.CANDIDATE},
            )
            candidate.concept = concept

        candidate.save(update_fields=["disposition", "disposition_reason", "disposition_at", "concept"])

    return decision


def assemble_evidence_packet(*, run: DiscoveryRun, candidate: RunCandidate) -> EvidencePacket:
    """§9 4C / §10: exact-mention retrieval only (no embeddings yet -- P8).
    Bounded to the Run's own frozen CorpusSnapshot, so a packet stays
    reproducible against what the Run actually saw, not whatever the live
    corpus looks like today."""

    phrase = candidate.concept_or_phrase_key
    snapshot_revision_ids = set(run.corpus_snapshot.source_revision_ids)

    passages = list(
        Passage.objects.filter(text__icontains=phrase, revision_id__in=snapshot_revision_ids)
        .select_related("revision__document")
        .order_by("-revision__captured_at")
    )

    # Diversity across source documents (§10): keep at most one passage per
    # document up to the cap, same reasoning as the build spec's "spread
    # across documents, not just the highest-scoring hits."
    seen_documents: set = set()
    selected = []
    for passage in passages:
        document_id = passage.revision.document_id
        if document_id in seen_documents:
            continue
        seen_documents.add(document_id)
        selected.append(passage)
        if len(selected) >= MAX_PACKET_PASSAGES:
            break

    last_version = (
        EvidencePacket.objects.filter(run=run, candidate_key=phrase).order_by("-packet_version").first()
    )
    next_version = (last_version.packet_version + 1) if last_version else 1

    document_count = len(seen_documents)
    summary = (
        f'{len(selected)} passage(s) across {document_count} document(s) mention "{phrase}".'
        if selected
        else f'No passages in this Run\'s snapshot mention "{phrase}" exactly -- candidate may need an alias.'
    )

    return EvidencePacket.objects.create(
        run=run,
        candidate_key=phrase,
        subject_kind=EvidencePacket.SubjectKind.CONCEPT,
        source_revision_ids=[str(p.revision_id) for p in selected],
        passage_ids=[str(p.id) for p in selected],
        packet_version=next_version,
        summary=summary,
        status="draft",
    )


def packet_passage_detail(packet: EvidencePacket) -> list[dict]:
    """Dereferences a packet's passage_ids for display (§10: the UI
    separates source evidence from machine interpretation -- this is the
    source-evidence half). Case-insensitive first-occurrence offsets only;
    a passage can mention the phrase more than once, but one anchor is
    enough to open the source at the right span."""

    passages = (
        Passage.objects.filter(id__in=packet.passage_ids)
        .select_related("revision__document", "section")
    )
    by_id = {str(p.id): p for p in passages}

    phrase_lower = packet.candidate_key.lower()
    detail = []
    for passage_id in packet.passage_ids:
        passage = by_id.get(passage_id)
        if passage is None:
            continue
        text = passage.text
        start = text.lower().find(phrase_lower)
        end = start + len(packet.candidate_key) if start >= 0 else None
        excerpt_start = max(0, (start or 0) - 160)
        excerpt_end = min(len(text), (end or 0) + 160)
        detail.append(
            {
                "passage_id": passage_id,
                "document_title": passage.revision.document.title,
                "document_uri": passage.revision.document.uri,
                "source_key": passage.revision.document.source_key,
                "heading_path": passage.section.heading_path if passage.section else "",
                "revision_captured_at": passage.revision.captured_at,
                "quote_offsets": {"start": start, "end": end} if start >= 0 else None,
                "excerpt": text[excerpt_start:excerpt_end],
            }
        )
    return detail
