"""
Ariadne — run one real Discovery Run against the latest CorpusSnapshot
(build spec §3/§8-9; minimal-P5 scope decided 2026-10-12).

Scoring reuses the exact TF-IDF approach the P0 spike already validated
against this corpus (tools/ariadne-spike-p0.py's build_lexical_baseline)
rather than inventing a new one -- General Lens only (no ADR-weighting
pass; that comparison was P0's job, already done and reviewed). Known,
already-documented limitation carried forward unchanged: English
stopwords only, no project-specific stoplist yet (still to be built
iteratively with the CTO) and no spaCy noun-phrase extraction (still
needs a CTO-prompted install) -- 1-3 gram TF-IDF is a stand-in, same as
P0. This run does not fix that; it is not a new regression either.

boost_terms always appear as RunCandidates regardless of their raw
TF-IDF rank, scored by their own TF-IDF value (not artificially
inflated) -- matches the addendum's Lens definition ("boost terms:
emphasize without filtering").

Every RunCandidate is created with disposition="pending": Accept/
Decline/Defer/Drop is the CTO's review step (build spec workflow §4),
not something this command decides on its own.

Usage:
  ARIADNE_ENABLED=True python manage.py ariadne_run_discovery \\
      --lens-name "General" --boost-term Catalyst --boost-term Mixtape
"""

from __future__ import annotations

import sklearn
from django.core.management.base import BaseCommand
from django.utils import timezone
from sklearn.feature_extraction.text import TfidfVectorizer

from ariadne.models import (
    CorpusSnapshot, DiscoveryRun, EvidencePacket, Lens, LensVersion, Passage, RunCandidate,
)

TOP_N = 25


class Command(BaseCommand):
    help = "Run one real Discovery Run (General Lens, TF-IDF) against the latest CorpusSnapshot."

    def add_arguments(self, parser):
        parser.add_argument("--lens-name", default="General")
        parser.add_argument("--boost-term", action="append", default=[], dest="boost_terms")

    def handle(self, *args, lens_name, boost_terms, **options):
        snapshot = CorpusSnapshot.objects.order_by("-captured_at").first()
        if snapshot is None:
            self.stderr.write("No CorpusSnapshot found -- run ariadne_ingest_snapshot first.")
            return

        passages = list(
            Passage.objects.filter(revision_id__in=snapshot.source_revision_ids)
            .select_related("revision__document")
        )
        if not passages:
            self.stderr.write("CorpusSnapshot has no passages -- nothing to score.")
            return
        self.stdout.write(f"Scoring {len(passages)} passages from CorpusSnapshot {snapshot.id}.")

        boost_terms = [t.lower() for t in boost_terms] or ["catalyst", "mixtape"]

        lens, _ = Lens.objects.get_or_create(name=lens_name, defaults={"description": "TF-IDF general lens, no ADR weighting."})
        config = {"ngram_range": [1, 3], "min_df": 2, "stop_words": "english", "boost_terms": boost_terms}
        version_number = lens.versions.count() + 1
        lens_version = LensVersion.objects.create(
            lens=lens, version=version_number, config=config,
            config_hash=f"sha256:{hash(frozenset(boost_terms)) & 0xffffffff:x}",
        )
        lens.active_version = lens_version
        lens.save(update_fields=["active_version", "updated_at"])

        run = DiscoveryRun.objects.create(
            lens_version=lens_version,
            corpus_snapshot=snapshot,
            extractor_versions={"tfidf": "sklearn", "sklearn_version": sklearn.__version__},
            model_versions={},
            status=DiscoveryRun.Status.RUNNING,
            target_concept_count=TOP_N,
            started_at=timezone.now(),
        )

        texts = [p.text for p in passages]
        vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 3), min_df=2, max_features=20000)
        matrix = vectorizer.fit_transform(texts)
        scores = matrix.sum(axis=0).A1
        vocab = vectorizer.vocabulary_
        ranked = sorted(zip(vectorizer.get_feature_names_out(), scores), key=lambda x: -x[1])

        ranked_terms = [t for t, _ in ranked[:TOP_N]]
        for term in boost_terms:
            if term not in ranked_terms and term in vocab:
                ranked_terms.append(term)

        created = 0
        for rank, term in enumerate(ranked_terms, start=1):
            score = float(scores[vocab[term]]) if term in vocab else 0.0
            col = matrix[:, vocab[term]].toarray().ravel() if term in vocab else None
            top_idx = col.argsort()[::-1][:5] if col is not None else []

            candidate = RunCandidate.objects.create(
                run=run,
                concept_or_phrase_key=term,
                rank=rank,
                score=score,
                score_components={"tfidf_sum": score, "boosted": term in boost_terms},
                appearance_key=term,
                disposition=RunCandidate.Disposition.PENDING,
            )
            source_revision_ids = [str(passages[i].revision_id) for i in top_idx if col[i] > 0]
            passage_ids = [str(passages[i].id) for i in top_idx if col[i] > 0]
            EvidencePacket.objects.create(
                run=run,
                candidate_key=term,
                source_revision_ids=source_revision_ids,
                passage_ids=passage_ids,
                packet_version=1,
                summary=f"Top {len(passage_ids)} source document(s) by TF-IDF weight for '{term}'.",
                status="draft",
            )
            created += 1

        run.status = DiscoveryRun.Status.COMPLETED
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "completed_at", "updated_at"])

        self.stdout.write(self.style.SUCCESS(
            f"Run {run.id} completed: {created} candidates (pending review), "
            f"boost terms present: {[t for t in boost_terms if t in vocab]}."
        ))
        self.stdout.write("Top 10 candidates:")
        for c in run.candidates.order_by("rank")[:10]:
            self.stdout.write(f"  {c.rank:>2}. {c.concept_or_phrase_key!r} ({c.score:.3f})")
