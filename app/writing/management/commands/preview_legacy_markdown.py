"""Generate a read-only review manifest for a legacy Markdown archive."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from writing.importers.legacy_markdown_inventory import (
    inventory_legacy_archive,
    manifest_csv_rows,
)


class Command(BaseCommand):
    help = "Inventory legacy Markdown files without changing source files or database records."

    def add_arguments(self, parser):
        parser.add_argument("source", help="Directory containing the canonical source archive.")
        parser.add_argument("--format", choices=("json", "csv"), default="json")
        parser.add_argument("--output", help="Output file. Defaults to stdout.")

    def handle(self, *args, **options):
        try:
            manifest = inventory_legacy_archive(options["source"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        output = options.get("output")
        destination = Path(output).expanduser().resolve() if output else None
        if destination and not destination.parent.is_dir():
            raise CommandError(f"Output directory does not exist: {destination.parent}")

        if options["format"] == "json":
            rendered = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
            if destination:
                destination.write_text(rendered, encoding="utf-8")
            else:
                self.stdout.write(rendered, ending="")
        else:
            rows = manifest_csv_rows(manifest)
            fieldnames = list(rows[0]) if rows else []
            if destination:
                with destination.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
            else:
                writer = csv.DictWriter(self.stdout, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

        if destination:
            summary = manifest["summary"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"Inventoried {summary['file_count']} files; wrote {options['format'].upper()} to {destination}"
                )
            )
