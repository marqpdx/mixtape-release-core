"""
Ariadne — P9/P9a: Inquiry Runs and the Review artifact (build spec
§19.2-19.3, scoped with the CTO 2026-11-04).

Frame (propose sub-questions) and Draft (write the cited Review) are the
only two steps that need a generative model call. No model task registry
(§11) exists yet -- Spike Reconnaissance before this phase found Inkwell's
existing inkwell.client.service_generate (grammar-constrained generation
against a JSON schema) already covers what both need, so both route
through it rather than new infrastructure. A model step runs only when a
caller explicitly passes use_model=True -- this pass's stand-in for ST-3
consent, since there's no consent-dialog mechanism built yet and every
caller here is the superuser-gated workbench.

Gather, Map and Review-packet assembly are fully deterministic (§19.5).

Two things named explicitly as NOT built here, both flagged to the CTO
before this phase started:
  - §19.3 (time-ordered development) depends on Phase F's "dated concept
    events" (§14, explicitly "(later)", not in the current build order).
    An Inquiry here has no time-development view.
  - §19.2 step 6's "Accession" (addendum §4) is deliberately NOT built --
    Likeness/anchor/accession schema is under a standing hold since P5
    (2026-10-12). Inquiry.standing_review is a scoped substitute: a plain
    pointer, the same shape as Lens.active_version, not the real
    mechanism.
"""

from __future__ import annotations

import math

from django.utils import timezone

from inkwell.client import service_generate

from .embedding import embed_texts, get_vectors
from .models import (
    CorpusSnapshot,
    EvidencePacket,
    Inquiry,
    InquiryReview,
    InquiryRun,
    InquiryTheme,
    Passage,
)
from .search import hybrid_search

MAX_GATHER_PASSAGES = 150
MAX_PER_DOCUMENT = 5
CLUSTER_SIMILARITY_THRESHOLD = 0.78


class ModelConsentRequired(Exception):
    """Raised when a step needs a model call but use_model wasn't set
    (§19.5: a model step runs only on explicit approval)."""


def create_inquiry(*, question: str, actor=None) -> Inquiry:
    return Inquiry.objects.create(question=question, created_by=actor)


# ---------------------------------------------------------------------------
# Step 1: Frame
# ---------------------------------------------------------------------------

def propose_sub_questions(inquiry: Inquiry) -> list[dict]:
    """Model-assisted proposal only -- never auto-approved. §19.2 step 1:
    'the person edits and approves them; nothing is gathered before
    approval.'"""
    schema = {
        "type": "object",
        "properties": {
            "sub_questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "search_terms": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["text", "search_terms"],
                },
            },
        },
        "required": ["sub_questions"],
    }
    result = service_generate(
        prompt=(
            f"Question: {inquiry.question}\n\n"
            "Propose 2-5 sub-questions that would need to be answered to address "
            "this question using an existing body of written material, each with "
            "search terms (including likely synonyms) to find relevant passages."
        ),
        system_prompt="You decompose a question into sub-questions and search terms. Output only the schema's JSON.",
        schema=schema,
        max_tokens=512,
    )
    proposed = result.get("result", {}).get("sub_questions", [])
    return [
        {"text": sq["text"], "approved": False, "search_terms": sq.get("search_terms", [])}
        for sq in proposed
    ]


def frame_inquiry(inquiry: Inquiry, *, sub_questions: list[dict] | None = None, use_model: bool = False) -> Inquiry:
    """The person supplies sub_questions directly (no model call, no
    consent needed), or opts into Inkwell's proposal with use_model=True."""
    if sub_questions is None:
        if not use_model:
            raise ModelConsentRequired(
                "Frame needs either explicit sub_questions or use_model=True to ask Inkwell to propose them."
            )
        sub_questions = propose_sub_questions(inquiry)

    inquiry.sub_questions = sub_questions
    inquiry.save(update_fields=["sub_questions", "updated_at"])
    return inquiry


def approve_sub_questions(inquiry: Inquiry, *, approved_texts: list[str]) -> Inquiry:
    """The person's edit/approve step. Only approved sub-questions are
    gathered against."""
    approved_set = set(approved_texts)
    sub_questions = inquiry.sub_questions
    for sq in sub_questions:
        sq["approved"] = sq["text"] in approved_set
    inquiry.sub_questions = sub_questions
    if any(sq["approved"] for sq in sub_questions):
        inquiry.status = Inquiry.Status.GATHERING
    inquiry.save(update_fields=["sub_questions", "status", "updated_at"])
    return inquiry


# ---------------------------------------------------------------------------
# Step 2: Gather
# ---------------------------------------------------------------------------

def gather_for_inquiry(inquiry: Inquiry) -> InquiryRun:
    """Hybrid retrieval per approved sub-question, deduplicated by
    passage, capped per document for diversity -- keeps contrary
    passages from the same document rather than taking only its single
    top hit."""
    approved = [sq for sq in inquiry.sub_questions if sq.get("approved")]
    if not approved:
        raise ValueError("No approved sub-questions to gather against -- run Frame and approve first.")

    snapshot = CorpusSnapshot.objects.order_by("-captured_at").first()
    if snapshot is None:
        raise ValueError("No CorpusSnapshot exists yet -- run ariadne_ingest_snapshot first.")

    run = InquiryRun.objects.create(
        inquiry=inquiry, corpus_snapshot=snapshot, status=InquiryRun.Status.RUNNING, started_at=timezone.now(),
    )

    pool: dict[str, dict] = {}
    per_document_count: dict[str, int] = {}
    for sq in approved:
        terms = [sq["text"], *sq.get("search_terms", [])]
        for term in terms:
            for hit in hybrid_search(term, limit=20):
                passage_id = hit["passage_id"]
                if passage_id in pool:
                    continue
                doc_key = hit["source_key"]
                if per_document_count.get(doc_key, 0) >= MAX_PER_DOCUMENT:
                    continue
                pool[passage_id] = hit
                per_document_count[doc_key] = per_document_count.get(doc_key, 0) + 1
                if len(pool) >= MAX_GATHER_PASSAGES:
                    break
            if len(pool) >= MAX_GATHER_PASSAGES:
                break
        if len(pool) >= MAX_GATHER_PASSAGES:
            break

    run.gathered_passage_ids = list(pool.keys())
    run.status = InquiryRun.Status.COMPLETED
    run.completed_at = timezone.now()
    run.save(update_fields=["gathered_passage_ids", "status", "completed_at", "updated_at"])

    inquiry.status = Inquiry.Status.MAPPING
    inquiry.save(update_fields=["status", "updated_at"])
    return run


# ---------------------------------------------------------------------------
# Step 3: Map
# ---------------------------------------------------------------------------

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def map_inquiry_run(run: InquiryRun) -> list[InquiryTheme]:
    """Deterministic clustering over the Gather pool via passage
    embeddings (cosine similarity), single-link greedy grouping. No
    model call -- labels are left blank; label_theme() below is the
    separate, explicitly-consented step for naming a cluster, never for
    forming one (§19.2 step 3: 'a model may only label themes')."""
    passage_ids = run.gathered_passage_ids
    passages = {str(p.id): p for p in Passage.objects.filter(id__in=passage_ids)}

    vectors = get_vectors(passage_ids)
    missing = [pid for pid in passage_ids if pid not in vectors and pid in passages]
    if missing:
        fresh = embed_texts([passages[pid].text for pid in missing])
        for pid, vector in zip(missing, fresh):
            vectors[pid] = vector

    unassigned = [pid for pid in passage_ids if pid in vectors]
    clusters: list[list[str]] = []
    while unassigned:
        seed = unassigned.pop(0)
        cluster = [seed]
        remaining = []
        for pid in unassigned:
            if _cosine_similarity(vectors[seed], vectors[pid]) >= CLUSTER_SIMILARITY_THRESHOLD:
                cluster.append(pid)
            else:
                remaining.append(pid)
        unassigned = remaining
        clusters.append(cluster)

    ungrouped = [pid for pid in passage_ids if pid not in vectors]
    if ungrouped:
        clusters.append(ungrouped)

    run.themes.all().delete()
    themes = []
    for rank, cluster in enumerate(sorted(clusters, key=len, reverse=True)):
        themes.append(InquiryTheme.objects.create(run=run, passage_ids=cluster, rank=rank))

    run.inquiry.status = Inquiry.Status.DRAFTING
    run.inquiry.save(update_fields=["status", "updated_at"])
    return themes


def label_theme(theme: InquiryTheme, *, use_model: bool = False) -> InquiryTheme:
    """Separate, optional model step: label a theme already formed
    deterministically above."""
    if not use_model:
        raise ModelConsentRequired("label_theme needs use_model=True (§19.5 consent).")
    passages = Passage.objects.filter(id__in=theme.passage_ids)[:5]
    excerpt_text = "\n---\n".join(p.text[:400] for p in passages)
    result = service_generate(
        prompt=f"Passages:\n{excerpt_text}\n\nIn 3-8 words, name the shared theme of these passages.",
        system_prompt="Output only the schema's JSON.",
        schema={"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"]},
        max_tokens=64,
    )
    theme.label = result.get("result", {}).get("label", "")[:256]
    theme.label_source = InquiryTheme.LabelSource.MODEL
    theme.save(update_fields=["label", "label_source", "updated_at"])
    return theme


# ---------------------------------------------------------------------------
# Step 4: Review packets
# ---------------------------------------------------------------------------

def assemble_theme_packet(theme: InquiryTheme) -> EvidencePacket:
    """One packet per theme -- same contract as P6's assemble_evidence_packet
    but subject_kind=inquiry_theme, bound to an InquiryRun instead of a
    DiscoveryRun (the generality §19.6 asked P6 to keep)."""
    passages = list(Passage.objects.filter(id__in=theme.passage_ids).select_related("revision__document"))
    document_ids = {p.revision.document_id for p in passages}
    summary = f"{len(passages)} passage(s) across {len(document_ids)} document(s)"
    if theme.label:
        summary += f' -- "{theme.label}"'

    last_version = (
        EvidencePacket.objects.filter(inquiry_run=theme.run, candidate_key=str(theme.id))
        .order_by("-packet_version")
        .first()
    )
    next_version = (last_version.packet_version + 1) if last_version else 1

    return EvidencePacket.objects.create(
        inquiry_run=theme.run,
        candidate_key=str(theme.id),
        subject_kind=EvidencePacket.SubjectKind.INQUIRY_THEME,
        source_revision_ids=[str(p.revision_id) for p in passages],
        passage_ids=[str(p.id) for p in passages],
        packet_version=next_version,
        summary=summary,
        status="draft",
    )


# ---------------------------------------------------------------------------
# Step 5: Draft
# ---------------------------------------------------------------------------

def draft_review(run: InquiryRun, *, use_model: bool = False) -> InquiryReview:
    """A Review whose every claim cites one or more passages by id. §9
    4E's rule applied directly: a claim citing a passage id outside the
    Gather pool has that id stripped, not downgraded with a soft note --
    it cannot have come from material this Run actually saw. A claim left
    with zero citations after stripping is rendered as interpretation,
    never as a cited fact."""
    if not use_model:
        raise ModelConsentRequired(
            "Draft needs use_model=True (§19.5 consent) -- it is the one step that must generate prose."
        )

    pool_ids = set(run.gathered_passage_ids)
    passages = {
        str(p.id): p
        for p in Passage.objects.filter(id__in=run.gathered_passage_ids).select_related("revision__document")
    }

    excerpts = []
    for theme in run.themes.order_by("rank"):
        for pid in theme.passage_ids[:8]:
            passage = passages.get(pid)
            if passage:
                excerpts.append(f"[{pid}] ({passage.revision.document.title}): {passage.text[:500]}")

    schema = {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "passage_ids": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["text", "passage_ids"],
                },
            },
        },
        "required": ["claims"],
    }
    result = service_generate(
        prompt=(
            f"Question: {run.inquiry.question}\n\n"
            "Excerpts (cite by the bracketed id, exactly as given):\n" + "\n".join(excerpts) + "\n\n"
            "Write a literature review answering the question. Every factual claim must cite "
            "one or more of the bracketed passage ids that support it. A claim with no supporting "
            "excerpt should have an empty passage_ids list -- it will be shown as your own interpretation."
        ),
        system_prompt="Output only the schema's JSON. Never invent a passage id not given in the excerpts.",
        schema=schema,
        max_tokens=1536,
    )
    claims = result.get("result", {}).get("claims", [])

    citations = []
    uncited_count = 0
    for i, claim in enumerate(claims):
        requested_ids = claim.get("passage_ids", [])
        cited_ids = [pid for pid in requested_ids if pid in pool_ids]
        rejected_ids = [pid for pid in requested_ids if pid not in pool_ids]
        interpretation = len(cited_ids) == 0
        if interpretation:
            uncited_count += 1
        citation = {
            "id": f"c{i}",
            "text": claim.get("text", ""),
            "passage_ids": cited_ids,
            "interpretation": interpretation,
            "status": "proposed",
            "amended_text": None,
        }
        if rejected_ids:
            citation["rejected_passage_ids"] = rejected_ids
        citations.append(citation)

    body_markdown = _render_review_markdown(run.inquiry.question, citations, passages)

    last_version = InquiryReview.objects.filter(inquiry=run.inquiry).order_by("-version").first()
    next_version = (last_version.version + 1) if last_version else 1
    review = InquiryReview.objects.create(
        inquiry=run.inquiry,
        run=run,
        version=next_version,
        body_markdown=body_markdown,
        citations=citations,
        uncited_claim_count=uncited_count,
        status=InquiryReview.Status.DRAFT,
    )
    run.inquiry.status = Inquiry.Status.CURATING
    run.inquiry.save(update_fields=["status", "updated_at"])
    return review


def _render_review_markdown(question: str, citations: list[dict], passages: dict) -> str:
    lines = [f"# {question}", ""]
    footnote_ids: dict[str, bool] = {}
    for citation in citations:
        if citation["status"] == "struck":
            continue
        text = citation["amended_text"] or citation["text"]
        if citation["interpretation"]:
            lines.append(f"{text} *(interpretation, uncited)*")
        else:
            marks = " ".join(f"[^{pid[:8]}]" for pid in citation["passage_ids"])
            lines.append(f"{text} {marks}")
            for pid in citation["passage_ids"]:
                footnote_ids.setdefault(pid, True)
        lines.append("")

    if footnote_ids:
        lines.append("---")
        lines.append("")
        for pid in footnote_ids:
            passage = passages.get(pid)
            if passage:
                lines.append(f"[^{pid[:8]}]: {passage.revision.document.title} -- {passage.text[:160]}...")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step 6: Curate (minus Accession -- see module note)
# ---------------------------------------------------------------------------

def curate_citation(
    review: InquiryReview, *, citation_id: str, action: str, amended_text: str | None = None
) -> InquiryReview:
    """Accept, amend or strike one claim. body_markdown is always
    regenerated from the mutated citations list -- never hand-edited
    directly."""
    if action not in {"accept", "amend", "strike"}:
        raise ValueError(f"Unknown curation action: {action}")

    citations = review.citations
    found = False
    for citation in citations:
        if citation["id"] == citation_id:
            found = True
            if action == "accept":
                citation["status"] = "accepted"
            elif action == "strike":
                citation["status"] = "struck"
            elif action == "amend":
                citation["status"] = "amended"
                citation["amended_text"] = amended_text
            break
    if not found:
        raise ValueError(f"No citation {citation_id} on this review.")

    all_passage_ids = [pid for c in citations for pid in c["passage_ids"]]
    passages = {
        str(p.id): p for p in Passage.objects.filter(id__in=all_passage_ids).select_related("revision__document")
    }
    review.citations = citations
    review.body_markdown = _render_review_markdown(review.inquiry.question, citations, passages)
    review.save(update_fields=["citations", "body_markdown", "updated_at"])
    return review


def accession_review(review: InquiryReview) -> Inquiry:
    """Scoped substitute for §19.2 step 6's Accession (see module note) --
    a plain standing-review pointer, not the real Likeness/accession
    mechanism. Explicit lineage (CTO, 2026-11-04): if this inquiry already
    has a standing review, this one records it as superseded_review --
    the one piece of step 6 ("with lineage when a later Run supersedes
    it") worth keeping even in the scoped-down version, since it's a
    single field, not the rest of Likeness (branches, anchors, honing
    ratio, shadow log)."""
    inquiry = review.inquiry
    if inquiry.standing_review_id and inquiry.standing_review_id != review.id:
        review.superseded_review = inquiry.standing_review

    review.status = InquiryReview.Status.CURATED
    review.save(update_fields=["superseded_review", "status", "updated_at"])
    inquiry.standing_review = review
    inquiry.status = Inquiry.Status.DONE
    inquiry.save(update_fields=["standing_review", "status", "updated_at"])
    return inquiry
