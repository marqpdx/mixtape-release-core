"""Ariadne — P8: embed every Passage not yet embedded into Ariadne's
Qdrant collection (idempotent; creates the collection on first run)."""

from django.core.management.base import BaseCommand

from ariadne.embedding import embed_pending_passages


class Command(BaseCommand):
    help = "Embed any Passage rows not yet embedded into Ariadne's Qdrant collection (P8)."

    def handle(self, *args, **options):
        count = embed_pending_passages()
        self.stdout.write(self.style.SUCCESS(f"Embedded {count} passage(s)."))
