from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ops.models import BuildLogEntry


FRONTMATTER_DELIMITER = "---"
COMMIT_SEPARATOR = " — "


class Command(BaseCommand):
    help = "Ingest build log markdown files into the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--inbox-dir",
            default=None,
            help="Path to the build-log-inbox directory.",
        )

    def handle(self, *args, **options):
        inbox_dir = options.get("inbox_dir")
        if not inbox_dir:
            raise CommandError("--inbox-dir is required.")

        inbox_path = Path(inbox_dir).expanduser()
        if not inbox_path.exists():
            raise CommandError(f"Inbox directory does not exist: {inbox_path}")
        if not inbox_path.is_dir():
            raise CommandError(f"Inbox path is not a directory: {inbox_path}")

        created_count = 0
        updated_count = 0
        skipped_count = 0

        for file_path in sorted(inbox_path.glob("*.md")):
            parsed_entry = self._parse_file(file_path)
            if parsed_entry is None:
                skipped_count += 1
                continue

            defaults = {
                "commit_message": parsed_entry["commit_message"],
                "repo": parsed_entry["repo"],
                "date": parsed_entry["date"],
                "work_effort": parsed_entry["work_effort"],
                "body": parsed_entry["body"],
                "source_filename": file_path.name,
            }
            _, created = BuildLogEntry.objects.update_or_create(
                commit_hash=parsed_entry["commit_hash"],
                defaults=defaults,
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Ingested build log entries: created={created_count}, "
                f"updated={updated_count}, skipped={skipped_count}"
            )
        )

    def _parse_file(self, file_path):
        try:
            raw_text = file_path.read_text(encoding="utf-8")
            metadata, body = self._split_frontmatter(raw_text)
            commit_hash, commit_message = self._parse_commit(metadata.get("commit", ""))
            entry_date = self._parse_date(metadata.get("date", ""))
            repo = metadata.get("repo", "").strip()
            if not repo:
                raise ValueError("Missing repo field.")

            return {
                "commit_hash": commit_hash,
                "commit_message": commit_message,
                "repo": repo,
                "date": entry_date,
                "work_effort": metadata.get("work_effort", "").strip(),
                "body": body.strip(),
            }
        except Exception as exc:
            self.stderr.write(
                self.style.WARNING(f"Skipping {file_path.name}: {exc}")
            )
            return None

    def _split_frontmatter(self, raw_text):
        lines = raw_text.splitlines()
        if len(lines) < 3 or lines[0].strip() != FRONTMATTER_DELIMITER:
            raise ValueError("Missing opening frontmatter delimiter.")

        closing_index = None
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == FRONTMATTER_DELIMITER:
                closing_index = index
                break

        if closing_index is None:
            raise ValueError("Missing closing frontmatter delimiter.")

        metadata = {}
        for line in lines[1:closing_index]:
            stripped_line = line.strip()
            if not stripped_line:
                continue
            if ":" not in stripped_line:
                raise ValueError(f"Malformed frontmatter line: {line}")
            key, value = stripped_line.split(":", 1)
            metadata[key.strip()] = value.strip()

        body = "\n".join(lines[closing_index + 1 :]).strip()
        return metadata, body

    def _parse_commit(self, commit_value):
        commit_value = commit_value.strip()
        if not commit_value:
            raise ValueError("Missing commit field.")
        if COMMIT_SEPARATOR not in commit_value:
            raise ValueError("Commit field must contain an em dash separator.")

        commit_hash, commit_message = commit_value.split(COMMIT_SEPARATOR, 1)
        commit_hash = commit_hash.strip()
        commit_message = commit_message.strip()
        if not commit_hash:
            raise ValueError("Commit hash is empty.")

        return commit_hash, commit_message

    def _parse_date(self, date_value):
        date_value = date_value.strip()
        if not date_value:
            raise ValueError("Missing date field.")
        try:
            return date.fromisoformat(date_value)
        except ValueError as exc:
            raise ValueError(f"Invalid date field: {date_value}") from exc
