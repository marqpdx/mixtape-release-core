# profiles/management/commands/migrate_public_media.py

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from mixtape.storage_backends import PublicMediaStorage
from utils.storage.storage_utils import is_absolute_url


class Command(BaseCommand):
    help = (
        "Copy existing profile/group avatar and background images from the "
        "default (signed) storage to PublicMediaStorage, so they can be "
        "served unsigned. Does not touch any model field -- the storage key "
        "stays the same; only the storage backend used to resolve its URL "
        "changes (see public_key_to_url() vs key_to_url()). Idempotent: "
        "skips any key that already exists in PublicMediaStorage. See "
        "puddlejump/features/image-handling/image-handling-build-plan.md."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be copied without writing anything.",
        )

    def handle(self, *args, **options):
        from groups.models import Group
        from profiles.models import UserProfile

        dry_run = options["dry_run"]
        public_storage = PublicMediaStorage()

        copied = 0
        skipped_existing = 0
        skipped_absolute = 0
        skipped_empty = 0
        failed = 0

        fields_by_model = [
            (UserProfile, ["profile_image", "background_image"]),
            (Group, ["profile_image_path", "background_image_path"]),
        ]

        for model, field_names in fields_by_model:
            for field_name in field_names:
                queryset = model.objects.exclude(**{field_name: ""}).exclude(**{f"{field_name}__isnull": True})
                for obj in queryset.iterator():
                    key = getattr(obj, field_name)

                    if not key:
                        skipped_empty += 1
                        continue

                    if is_absolute_url(key):
                        # Already an external URL (e.g. legacy avatar_url
                        # fallback data) -- nothing in our storage to copy.
                        skipped_absolute += 1
                        continue

                    if public_storage.exists(key):
                        skipped_existing += 1
                        continue

                    label = f"{model.__name__}.{field_name} ({obj.pk}): {key}"

                    if dry_run:
                        self.stdout.write(f"  [dry-run] would copy: {label}")
                        copied += 1
                        continue

                    try:
                        with default_storage.open(key, "rb") as source:
                            content = source.read()
                        public_storage.save(key, ContentFile(content))
                        copied += 1
                    except Exception as exc:
                        failed += 1
                        self.stderr.write(self.style.ERROR(f"  FAILED: {label} -- {exc}"))

        label = "Would copy" if dry_run else "Copied"
        self.stdout.write(
            self.style.SUCCESS(
                f"{label} {copied} objects to public storage. "
                f"Skipped {skipped_existing} already migrated, "
                f"{skipped_absolute} absolute/external URLs, "
                f"{skipped_empty} empty fields. "
                f"{failed} failed."
            )
        )
