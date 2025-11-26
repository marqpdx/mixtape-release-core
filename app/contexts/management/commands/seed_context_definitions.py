# apps/contextual/management/commands/seed_context_definitions.py

'''
Example usage:

Seed defaults:
> python manage.py seed_context_definitions

Seed from a JSON file:
> python manage.py seed_context_definitions --from-file ./context_defs.json

`context_defs.json` example:

[
  {"slug": "course-default-chat", "name": "Course Default Conversation"},
  {"slug": "group-default-chat", "name": "Group Default Conversation"},
  {"slug": "cohort-chat", "name": "Cohort Conversation"},
  {"slug": "office-hours", "name": "Office Hours Chat", "description": "Scheduled teacher Q&A"}
]

Preview changes only:
> python manage.py seed_context_definitions --dry-run

Prune anything not in the provided set:
python manage.py seed_context_definitions --from-file ./context_defs.json --prune

'''





import json
from pathlib import Path
from typing import Iterable, Dict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from contexts.models import ContextDefinition



DEFAULT_DEFS = [
    {"slug": "course-default-chat", "name": "Course Default Conversation",
     "description": "Default chat for each Course"},
    {"slug": "group-default-chat", "name": "Group Default Conversation",
     "description": "Default chat for each Group"},
    {"slug": "cohort-chat", "name": "Cohort Conversation",
     "description": "Default chat for each Course Cohort"},
]


def load_defs_from_file(path: Path) -> Iterable[Dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise CommandError(f"Failed to read/parse JSON file '{path}': {e}")
    if not isinstance(data, list):
        raise CommandError("Seed file must contain a JSON list of objects.")
    required = {"slug", "name"}
    for row in data:
        if not isinstance(row, dict) or not required.issubset(row.keys()):
            raise CommandError(
                f"Each row must include at least {sorted(required)}. Got: {row}"
            )
    return data


class Command(BaseCommand):
    help = "Seed ContextDefinition vocabulary (idempotent). Optionally from a JSON file."

    def add_arguments(self, parser):
        parser.add_argument(
            "--from-file",
            type=str,
            help="Path to JSON file with a list of {slug, name, description?}.",
        )
        parser.add_argument(
            "--prune",
            action="store_true",
            help="Delete ContextDefinitions NOT present in the provided set.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without writing to the database.",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        dry_run = opts["dry_run"]
        prune = opts["prune"]
        file_path = opts.get("from_file")

        if file_path:
            defs = list(load_defs_from_file(Path(file_path)))
        else:
            defs = list(DEFAULT_DEFS)

        wanted_by_slug = {d["slug"]: d for d in defs}
        existing = {cd.slug: cd for cd in ContextDefinition.objects.all()}

        created, updated, unchanged = 0, 0, 0

        # Upsert
        for slug, payload in wanted_by_slug.items():
            name = payload.get("name", slug)
            description = payload.get("description", "")
            if slug in existing:
                cd = existing[slug]
                if cd.name != name or (cd.description or "") != (description or ""):
                    self.stdout.write(f"UPDATE {slug}: name='{name}', description updated")
                    if not dry_run:
                        cd.name = name
                        cd.description = description
                        cd.save(update_fields=["name", "description"])
                    updated += 1
                else:
                    unchanged += 1
            else:
                self.stdout.write(f"CREATE {slug}: name='{name}'")
                if not dry_run:
                    ContextDefinition.objects.create(
                        slug=slug, name=name, description=description
                    )
                created += 1

        # Prune (optional)
        pruned = 0
        if prune:
            to_delete = set(existing.keys()) - set(wanted_by_slug.keys())
            for slug in sorted(to_delete):
                self.stdout.write(f"DELETE {slug}")
                if not dry_run:
                    existing[slug].delete()
                pruned += 1

        # Summary
        self.stdout.write(self.style.SUCCESS(
            f"Done. created={created}, updated={updated}, unchanged={unchanged}, pruned={pruned}"
        ))

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry-run mode: no changes were written."))
