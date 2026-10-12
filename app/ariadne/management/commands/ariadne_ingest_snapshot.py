"""
Ariadne — ingest the real Puddlejump corpus into P4's tables and freeze a
CorpusSnapshot (build spec §3/§4).

Idempotent per source document: a SourceDocument is upserted on
(source_system, source_key); a new SourceRevision is only created when
content_hash changes, matching build spec §4's revision-fingerprint
intent. Chunking is deliberately NOT implemented here -- still an
explicitly deferred decision ("stays deferred, in-flow", P0 review,
2026-10-11) -- so each revision gets exactly one Passage covering the
whole stripped document text, with no SourceSection. Real chunking
replaces this later without changing the schema.

Usage:
  ARIADNE_ENABLED=True python manage.py ariadne_ingest_snapshot
"""

from __future__ import annotations

import hashlib

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from ariadne.corpus import enumerate_documents
from ariadne.models import CorpusSnapshot, Passage, SourceDocument, SourceRevision


class Command(BaseCommand):
    help = "Ingest the live Puddlejump corpus into SourceDocument/SourceRevision/Passage and freeze a CorpusSnapshot."

    def handle(self, *args, **options):
        docs = enumerate_documents()
        self.stdout.write(f"Enumerated {len(docs)} documents from the corpus connector.")

        revision_ids = []
        created_docs = updated_revisions = unchanged = 0

        with transaction.atomic():
            for doc in docs:
                source_doc, created = SourceDocument.objects.get_or_create(
                    source_system="puddlejump",
                    source_key=doc.rel_path,
                    defaults={
                        "title": doc.headings[0][1] if doc.headings else doc.rel_path,
                        "document_type": "adr" if doc.is_adr else "document",
                        "uri": doc.rel_path,
                    },
                )
                if created:
                    created_docs += 1

                latest = source_doc.current_revision
                if latest is not None and latest.content_hash == doc.content_hash:
                    unchanged += 1
                    revision_ids.append(str(latest.id))
                    continue

                revision = SourceRevision.objects.create(
                    document=source_doc,
                    content_hash=doc.content_hash,
                    captured_at=timezone.now(),
                    parser_version="ariadne.corpus/yaml-only-2026-10-12",
                    status="captured",
                )
                Passage.objects.create(
                    revision=revision,
                    section=None,
                    ordinal=0,
                    text=doc.stripped_text,
                    content_hash=doc.content_hash,
                    embedding_status="none",
                )
                source_doc.current_revision = revision
                source_doc.save(update_fields=["current_revision", "updated_at"])
                updated_revisions += 1
                revision_ids.append(str(revision.id))

            manifest_hash = hashlib.sha256("\n".join(sorted(revision_ids)).encode()).hexdigest()
            snapshot = CorpusSnapshot.objects.create(
                manifest_hash=f"sha256:{manifest_hash}",
                source_revision_ids=revision_ids,
                captured_at=timezone.now(),
            )

        self.stdout.write(self.style.SUCCESS(
            f"Ingest complete: {created_docs} new documents, {updated_revisions} new revisions, "
            f"{unchanged} unchanged. CorpusSnapshot {snapshot.id} ({len(revision_ids)} revisions)."
        ))
