from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from writing.models import WorkingDocument, WritingPiece, body_json_has_content


class Command(BaseCommand):
    help = "Inspect one Issue draft and reconcile its WritingPiece title/empty flag. Dry-run by default."

    def add_arguments(self, parser):
        parser.add_argument("--working-document-id", required=True)
        parser.add_argument("--execute", action="store_true")

    def handle(self, *args, **options):
        with transaction.atomic():
            draft = (
                WorkingDocument.objects.select_related("piece")
                .filter(pk=options["working_document_id"])
                .first()
            )
            if not draft:
                raise CommandError("WorkingDocument not found.")
            piece = draft.piece
            if piece.status != "draft":
                raise CommandError("Only draft pieces can be reconciled.")
            if not piece.issue_placements.exists():
                raise CommandError("This piece has no Issue placement.")
            latest = piece.working_copies.order_by("-last_saved_at", "-pk").first()
            if latest.pk != draft.pk:
                raise CommandError("This is not the latest WorkingDocument for the piece.")
            if len(draft.title) > WritingPiece._meta.get_field("title").max_length:
                raise CommandError("Draft title exceeds the WritingPiece title limit.")

            expected_empty = not body_json_has_content(draft.body_json)
            self.stdout.write(
                f"WorkingDocument {draft.pk}: piece={piece.pk} "
                f"draft_title={draft.title!r} piece_title={piece.title!r} "
                f"draft_bytes={len(str(draft.body_json).encode('utf-8'))} "
                f"is_empty={piece.is_empty} expected_is_empty={expected_empty} "
                f"revision={draft.auto_save_count}"
            )
            if options["execute"]:
                updates = {}
                if piece.title != draft.title:
                    updates["title"] = draft.title
                if piece.is_empty != expected_empty:
                    updates["is_empty"] = expected_empty
                if updates:
                    WritingPiece.objects.filter(pk=piece.pk).update(**updates)
                    self.stdout.write(self.style.SUCCESS("Draft discovery metadata reconciled."))
                else:
                    self.stdout.write("No metadata change needed.")
                self.stdout.write("Draft body was not promoted or published.")
            else:
                self.stdout.write("Dry run only. Re-run with --execute to reconcile title and empty flag.")
