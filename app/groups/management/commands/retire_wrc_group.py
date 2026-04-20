"""
One-off maintenance command for the Wellness Resource Center group swap.

Usage:
    python manage.py retire_wrc_group
    python manage.py retire_wrc_group --dry-run
"""

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from groups.models import Group


DEPRECATED_SLUG = "wellness-resource-center"
SURVIVING_SLUG = "community-health-explorations"
RENAMED_DEPRECATED_SLUG = "zzz-wrc"
RENAMED_DEPRECATED_TITLE = "ZZ Deprecated"
RENAMED_SURVIVING_SLUG = "wellness-resource-center"
RENAMED_SURVIVING_TITLE = "Wellness Resource Center"


class Command(BaseCommand):
    help = (
        "Rename the two WRC-related groups, reassign sponsor-backed content to the "
        "surviving group, and delete the deprecated group."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report the planned changes and abort before writing.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        sponsor_models = self._get_sponsor_models()
        total_reassigned = 0
        writing_piece_rows = []

        with transaction.atomic():
            deprecated_group, surviving_group = self._lock_groups()
            group_content_type = ContentType.objects.get_for_model(Group)

            collision_lines, sponsor_counts, writing_piece_rows = self._collect_sponsor_changes(
                sponsor_models=sponsor_models,
                group_content_type=group_content_type,
                deprecated_group=deprecated_group,
                surviving_group=surviving_group,
            )

            self._print_plan(
                deprecated_group=deprecated_group,
                surviving_group=surviving_group,
                sponsor_counts=sponsor_counts,
                writing_piece_rows=writing_piece_rows,
                dry_run=dry_run,
            )

            if collision_lines:
                raise CommandError(
                    "Slug collisions detected for sponsor-backed content:\n"
                    + "\n".join(collision_lines)
                )

            if dry_run:
                transaction.set_rollback(True)
            else:
                self._rename_group(
                    group=deprecated_group,
                    new_slug=RENAMED_DEPRECATED_SLUG,
                    new_title=RENAMED_DEPRECATED_TITLE,
                )
                self._rename_group(
                    group=surviving_group,
                    new_slug=RENAMED_SURVIVING_SLUG,
                    new_title=RENAMED_SURVIVING_TITLE,
                )

                for model, count in sponsor_counts:
                    if not count:
                        continue
                    total_reassigned += model.objects.filter(
                        sponsor_content_type=group_content_type,
                        sponsor_object_id=deprecated_group.id,
                    ).update(
                        sponsor_content_type=group_content_type,
                        sponsor_object_id=surviving_group.id,
                    )

                deprecated_group.delete()

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run complete. No changes were written."))
            return

        self.stdout.write(
            self.style.SUCCESS(
                "Completed WRC group retirement. "
                f"Reassigned {total_reassigned} sponsor-backed rows and deleted "
                f"group {RENAMED_DEPRECATED_SLUG}."
            )
        )

    def _lock_groups(self):
        deprecated_group = (
            Group.objects.select_for_update()
            .filter(slug=DEPRECATED_SLUG)
            .first()
        )
        if deprecated_group is None:
            raise CommandError(f"Group with slug '{DEPRECATED_SLUG}' not found.")

        surviving_group = (
            Group.objects.select_for_update()
            .filter(slug=SURVIVING_SLUG)
            .first()
        )
        if surviving_group is None:
            raise CommandError(f"Group with slug '{SURVIVING_SLUG}' not found.")

        if deprecated_group.id == surviving_group.id:
            raise CommandError("Expected two distinct groups, found one.")

        slug_conflict = (
            Group.objects.select_for_update()
            .exclude(id__in=[deprecated_group.id, surviving_group.id])
            .filter(slug__in=[RENAMED_DEPRECATED_SLUG, RENAMED_SURVIVING_SLUG])
            .exists()
        )
        if slug_conflict:
            raise CommandError(
                "Another group already uses one of the destination slugs "
                f"('{RENAMED_DEPRECATED_SLUG}' or '{RENAMED_SURVIVING_SLUG}')."
            )

        return deprecated_group, surviving_group

    def _get_sponsor_models(self):
        sponsor_models = []
        for model in apps.get_models():
            if model._meta.abstract or model._meta.proxy:
                continue
            field_names = {field.name for field in model._meta.get_fields()}
            if {"sponsor_content_type", "sponsor_object_id"} <= field_names:
                sponsor_models.append(model)
        sponsor_models.sort(key=lambda model: model._meta.label_lower)
        return sponsor_models

    def _collect_sponsor_changes(
        self,
        *,
        sponsor_models,
        group_content_type,
        deprecated_group,
        surviving_group,
    ):
        collision_lines = []
        sponsor_counts = []
        writing_piece_rows = []

        for model in sponsor_models:
            qs = model.objects.filter(
                sponsor_content_type=group_content_type,
                sponsor_object_id=deprecated_group.id,
            )
            count = qs.count()
            sponsor_counts.append((model, count))
            if not count:
                continue

            if model._meta.label == "writing.WritingPiece":
                writing_piece_rows = list(
                    qs.order_by("slug").values_list("id", "slug", "title")
                )

            if not self._model_has_field(model, "slug"):
                continue

            slugs = list(qs.values_list("slug", flat=True))
            collisions = sorted(
                model.objects.filter(
                    sponsor_content_type=group_content_type,
                    sponsor_object_id=surviving_group.id,
                    slug__in=slugs,
                ).values_list("slug", flat=True)
            )
            if collisions:
                collision_lines.append(
                    f"- {model._meta.label}: {', '.join(collisions)}"
                )

        return collision_lines, sponsor_counts, writing_piece_rows

    def _rename_group(self, *, group, new_slug, new_title):
        if group.slug != new_slug and group.slug not in group.slug_history:
            group.slug_history.append(group.slug)
        group.slug = new_slug
        group.title = new_title
        group.save()

    def _model_has_field(self, model, field_name):
        try:
            model._meta.get_field(field_name)
        except Exception:
            return False
        return True

    def _print_plan(
        self,
        *,
        deprecated_group,
        surviving_group,
        sponsor_counts,
        writing_piece_rows,
        dry_run,
    ):
        prefix = "[DRY RUN] " if dry_run else ""
        self.stdout.write(
            f"{prefix}Deprecated group: {deprecated_group.title} ({deprecated_group.slug})"
        )
        self.stdout.write(
            f"{prefix}Surviving group: {surviving_group.title} ({surviving_group.slug})"
        )
        self.stdout.write(
            f"{prefix}Rename plan: "
            f"{DEPRECATED_SLUG} -> {RENAMED_DEPRECATED_SLUG}, "
            f"{SURVIVING_SLUG} -> {RENAMED_SURVIVING_SLUG}"
        )

        touched = [(model, count) for model, count in sponsor_counts if count]
        if not touched:
            self.stdout.write(f"{prefix}No sponsor-backed content needs reassignment.")
            return

        self.stdout.write(f"{prefix}Sponsor-backed rows to reassign:")
        for model, count in touched:
            self.stdout.write(f"  - {model._meta.label}: {count}")

        if writing_piece_rows:
            self.stdout.write(f"{prefix}WritingPiece rows to reassign:")
            WritingPiece = apps.get_model("writing", "WritingPiece")
            for piece_id, slug, title in writing_piece_rows:
                piece = WritingPiece.objects.get(id=piece_id)
                self.stdout.write(
                    "  - "
                    f"{piece_id} slug={slug} title={title!r} "
                    f"working_copies={piece.working_copies.count()}"
                )
