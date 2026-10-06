# folio/management/commands/index_folio_notes.py
#
# Backfill FolioNotes into Stackroom (Folio Notes PoC Phase 4) — for notes
# captured before retrieval existed, or after a Stackroom outage. Enqueues the
# same ingest task capture uses; already-synced, unchanged notes are skipped.

from django.core.management.base import BaseCommand
from django.db.models import Q

from folio.models import FolioNote


class Command(BaseCommand):
    help = "Enqueue Stackroom ingest for FolioNotes that have text."

    def add_arguments(self, parser):
        parser.add_argument("--user", help="Only this username's notes.")
        parser.add_argument("--force", action="store_true", help="Re-ingest even if already synced.")

    def handle(self, *args, **options):
        from django.contrib.contenttypes.models import ContentType

        from inkwell.tasks.stackroom_integration import ingest_object_task

        notes = FolioNote.objects.filter(created_by__isnull=False).exclude(
            Q(raw_text="") & Q(transcript_text="")
        )
        if options["user"]:
            notes = notes.filter(created_by__username=options["user"])

        ct = ContentType.objects.get_for_model(FolioNote, for_concrete_model=False)
        count = 0
        for note_id in notes.values_list("id", flat=True).iterator():
            ingest_object_task.apply_async(
                kwargs={
                    "content_type_id": ct.pk,
                    "object_id": str(note_id),
                    "reason": "folio_note_backfill",
                    "force": options["force"],
                },
                queue="commons",
            )
            count += 1
        self.stdout.write(self.style.SUCCESS(f"Enqueued Stackroom ingest for {count} FolioNote(s)."))
