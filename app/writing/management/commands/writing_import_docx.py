# writing/management/commands/writing_import_docx.py
"""
Import a .docx file into a WritingPiece with TipTap JSON body.

Usage:
    python manage.py writing_import_docx \
        --path /path/to/file.docx \
        --author user@example.com \
        --sponsor group:UUID \
        --kind dispatch \
        --enable-outline \
        --dry-run
"""

import hashlib
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from writing.importers.docx_to_tiptap import (
    docx_to_tiptap,
    generate_outline_from_headings,
    extract_title,
    count_nodes_by_type,
)
from writing.importers.docx_comments import extract_docx_comments
from writing.models import WritingPiece, ImportReceipt

User = get_user_model()


class Command(BaseCommand):
    help = "Import a .docx file into a WritingPiece as TipTap JSON"

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            required=True,
            help="Path to the .docx file",
        )
        parser.add_argument(
            "--author",
            required=True,
            help="Author user ID (UUID) or email address",
        )
        parser.add_argument(
            "--sponsor",
            required=True,
            help="Sponsor in format 'model_name:object_id' (e.g. 'group:abc-123' or 'user:def-456')",
        )
        parser.add_argument(
            "--kind",
            default="dispatch",
            choices=["post", "article", "dispatch", "forum", "announcement", "almanac", "page", "other"],
            help="Writing kind (default: dispatch)",
        )
        parser.add_argument(
            "--title",
            default=None,
            help="Title override (default: extracted from first heading or filename)",
        )
        parser.add_argument(
            "--addressed-to",
            default="public",
            choices=["public", "crossroads", "self"],
            help="Addressed to (default: public)",
        )
        parser.add_argument(
            "--enable-outline",
            action="store_true",
            help="Generate outline nodes from headings",
        )
        parser.add_argument(
            "--source-url",
            default=None,
            help="Original document URL (e.g. Google Docs link)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Skip idempotency check (import even if file was already imported)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and print stats without creating any records",
        )

    def handle(self, *args, **options):
        file_path = Path(options["path"])

        # Validate file exists
        if not file_path.exists():
            raise CommandError(f"File not found: {file_path}")
        if not file_path.suffix.lower() == ".docx":
            raise CommandError(f"Expected .docx file, got: {file_path.suffix}")

        # Read file and compute hash
        file_bytes = file_path.read_bytes()
        file_sha256 = hashlib.sha256(file_bytes).hexdigest()

        self.stdout.write(f"File: {file_path.name}")
        self.stdout.write(f"Size: {len(file_bytes):,} bytes")
        self.stdout.write(f"SHA-256: {file_sha256[:16]}...")

        # Idempotency check
        if not options["force"]:
            existing = ImportReceipt.objects.filter(source_sha256=file_sha256).first()
            if existing:
                self.stdout.write(self.style.WARNING(
                    f"Already imported as WritingPiece {existing.created_writing_piece_id} "
                    f"(receipt: {existing.id}). Use --force to import again."
                ))
                return

        # Resolve author
        author = self._resolve_author(options["author"])
        self.stdout.write(f"Author: {author.email}")

        # Resolve sponsor
        sponsor = self._resolve_sponsor(options["sponsor"])
        self.stdout.write(f"Sponsor: {sponsor}")

        # Parse DOCX
        self.stdout.write("Parsing .docx...")
        tiptap_json = docx_to_tiptap(file_bytes)

        # Extract comments
        comments = extract_docx_comments(str(file_path))
        if comments:
            self.stdout.write(f"Found {len(comments)} comments in document")

        # Determine title
        title = options["title"] or extract_title(tiptap_json) or file_path.stem
        self.stdout.write(f"Title: {title}")

        # Generate outline if requested
        outline_specs = []
        if options["enable_outline"]:
            outline_specs = generate_outline_from_headings(tiptap_json)
            self.stdout.write(f"Outline: {len(outline_specs)} sections from headings")

        # Stats
        node_counts = count_nodes_by_type(tiptap_json)
        self.stdout.write("\nNode counts:")
        for node_type, count in sorted(node_counts.items()):
            self.stdout.write(f"  {node_type}: {count}")

        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS("\n[DRY RUN] No records created."))
            return

        # Create records
        with transaction.atomic():
            piece = WritingPiece(
                author=author,
                title=title,
                body_json=tiptap_json,
                writing_kind=options["kind"],
                addressed_to=options["addressed_to"],
                enable_outline=options["enable_outline"],
            )
            piece.set_sponsor(sponsor)
            piece.save()

            # Create import receipt
            import_notes = {
                "node_counts": node_counts,
                "heading_count": len(outline_specs),
            }
            if comments:
                import_notes["comments"] = comments

            receipt = ImportReceipt.objects.create(
                source_type="docx",
                source_sha256=file_sha256,
                original_filename=file_path.name,
                source_url=options.get("source_url") or None,
                created_writing_piece=piece,
                imported_by=author,
                import_notes=import_notes,
            )

            # Create outline nodes if enabled
            if outline_specs:
                from dispatch.models import DispatchOutlineNode
                for spec in outline_specs:
                    DispatchOutlineNode.objects.create(
                        writing_piece=piece,
                        title=spec["title"],
                        order_index=spec["order_index"],
                        anchor_target=spec["anchor_target"],
                    )

        self.stdout.write(self.style.SUCCESS(
            f"\nCreated WritingPiece: {piece.id}"
            f"\n  Kind: {piece.writing_kind}"
            f"\n  Status: {piece.status}"
            f"\n  Reading time: {piece.reading_time} min"
            f"\n  Outline nodes: {len(outline_specs)}"
            f"\n  Import receipt: {receipt.id}"
        ))

    def _resolve_author(self, author_ref: str) -> "User":
        """Resolve author by UUID or email."""
        # Try UUID first
        try:
            import uuid
            uuid.UUID(author_ref)
            user = User.objects.get(id=author_ref)
            return user
        except (ValueError, User.DoesNotExist):
            pass

        # Try email
        try:
            return User.objects.get(email=author_ref)
        except User.DoesNotExist:
            raise CommandError(f"Author not found: {author_ref} (tried UUID and email)")

    def _resolve_sponsor(self, sponsor_ref: str):
        """
        Resolve sponsor from 'model_name:object_id' format.
        Example: 'group:abc-123' or 'user:def-456'
        """
        if ":" not in sponsor_ref:
            raise CommandError(
                f"Invalid sponsor format: {sponsor_ref}. "
                f"Expected 'model_name:object_id' or 'app_label.model_name:object_id' "
                f"(e.g. 'group:abc-123' or 'groups.group:abc-123')"
            )

        model_part, object_id = sponsor_ref.split(":", 1)

        try:
            if "." in model_part:
                app_label, model_name = model_part.split(".", 1)
                ct = ContentType.objects.get(app_label=app_label.lower(), model=model_name.lower())
            else:
                cts = ContentType.objects.filter(model=model_part.lower())
                if cts.count() > 1:
                    # Ambiguous — try common app labels
                    for app in ["groups", "users", "identity"]:
                        try:
                            ct = ContentType.objects.get(app_label=app, model=model_part.lower())
                            break
                        except ContentType.DoesNotExist:
                            continue
                    else:
                        labels = ", ".join(f"{c.app_label}.{c.model}" for c in cts)
                        raise CommandError(
                            f"Ambiguous content type '{model_part}'. "
                            f"Found: {labels}. Use 'app_label.model_name:object_id' format."
                        )
                elif cts.count() == 1:
                    ct = cts.first()
                else:
                    raise ContentType.DoesNotExist()
        except ContentType.DoesNotExist:
            raise CommandError(f"Unknown content type: {model_part}")

        model_class = ct.model_class()
        try:
            return model_class.objects.get(pk=object_id)
        except model_class.DoesNotExist:
            raise CommandError(f"{model_name} with ID {object_id} not found")
