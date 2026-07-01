# writing/management/commands/backfill_working_copies.py
"""
Backfill WorkingDocument rows for pieces that have canonical body_json but
no working copy for their author. This happens with imported documents where
the importer wrote piece.body_json but never created a WorkingDocument row.

Usage:
    python manage.py backfill_working_copies
    python manage.py backfill_working_copies --dry-run
    python manage.py backfill_working_copies --piece-id <uuid> [--piece-id <uuid> ...]

Safe to re-run — uses get_or_create and only writes when the existing
working copy body is empty.
"""

from django.core.management.base import BaseCommand
from writing.models import WritingPiece, WorkingDocument


def _has_content(body_json):
    return (
        body_json
        and isinstance(body_json, dict)
        and bool(body_json.get("content"))
    )


class Command(BaseCommand):
    help = "Backfill WorkingDocument rows from piece.body_json where missing or empty."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing to the DB.",
        )
        parser.add_argument(
            "--piece-id",
            dest="piece_ids",
            action="append",
            default=[],
            metavar="UUID",
            help="Limit to specific piece IDs (repeatable).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        piece_ids = options["piece_ids"]

        qs = WritingPiece.objects.select_related("author").filter(
            author__isnull=False
        )
        if piece_ids:
            qs = qs.filter(pk__in=piece_ids)

        created = 0
        updated = 0
        skipped = 0

        for piece in qs.iterator():
            if not _has_content(piece.body_json):
                skipped += 1
                continue

            wc = WorkingDocument.objects.filter(
                piece=piece, user=piece.author
            ).first()

            if wc is None:
                if dry_run:
                    self.stdout.write(
                        f"[DRY RUN] would create WC for piece {piece.pk} ({piece.title!r})"
                    )
                else:
                    WorkingDocument.objects.create(
                        piece=piece,
                        user=piece.author,
                        body_json=piece.body_json,
                    )
                    self.stdout.write(
                        f"Created WC for piece {piece.pk} ({piece.title!r})"
                    )
                created += 1

            elif not _has_content(wc.body_json):
                if dry_run:
                    self.stdout.write(
                        f"[DRY RUN] would populate empty WC for piece {piece.pk} ({piece.title!r})"
                    )
                else:
                    wc.body_json = piece.body_json
                    wc.save(update_fields=["body_json"])
                    self.stdout.write(
                        f"Populated WC for piece {piece.pk} ({piece.title!r})"
                    )
                updated += 1

            else:
                skipped += 1

        label = "[DRY RUN] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{label}Done — created: {created}, populated: {updated}, skipped: {skipped}"
            )
        )
