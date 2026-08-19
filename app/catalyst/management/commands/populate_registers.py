"""
management command: populate_registers

Reads each materialized register's _index.md, extracts individual entities
from the source file using Claude, and writes one .md file per entity.

Usage:
  python manage.py populate_registers <group_slug> [--job-id <uuid>] [--register <slug>] [--dry-run]

--register   limit to one register slug (e.g. recipes)
--job-id     read client_context from this parse job
--dry-run    print entities without writing files
"""

import re
import unicodedata
import uuid
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text)


def _unique_slug(slug: str, seen: set) -> str:
    base, n = slug, 1
    while slug in seen:
        slug = f"{base}-{n}"
        n += 1
    seen.add(slug)
    return slug


ENTITY_TEMPLATE = """\
---
id: {entry_id}
name: {name}
register: {register_slug}
source_file: {source_file}
extracted_at: {extracted_at}
{extra_fields}---

# {name}

{body}
"""


class Command(BaseCommand):
    help = "Populate registers with individual entity entries extracted by Claude"

    def add_arguments(self, parser):
        parser.add_argument("group_slug", type=str)
        parser.add_argument("--job-id", type=str, default=None)
        parser.add_argument("--register", type=str, default=None, help="Limit to one register slug")
        parser.add_argument("--timeout", type=int, default=240)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        from catalyst.services.parse_service import extract_entities
        from catalyst.api.views import _git, NOW_ISO
        import yaml  # pyyaml — already in requirements

        group_slug = options["group_slug"]
        only_register = options["register"]
        timeout = options["timeout"]
        dry_run = options["dry_run"]
        job_id = options["job_id"]

        # Optionally pull client_context from the parse job
        client_context = None
        if job_id:
            from catalyst.models import CatalystParseJob
            try:
                job = CatalystParseJob.objects.get(pk=job_id)
                client_context = job.client_context or None
                self.stdout.write(f"📋 Using client_context from job {job_id}")
            except CatalystParseJob.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"Job {job_id} not found — proceeding without client_context"))

        codex_root = Path(settings.CATALYST_CODEX_ROOT) / group_slug
        registers_dir = codex_root / "CONTENT" / "registers"

        if not registers_dir.exists():
            raise CommandError(f"No registers directory found at {registers_dir}")

        # Find all register dirs that have an _index.md
        register_dirs = sorted([d for d in registers_dir.iterdir() if d.is_dir() and (d / "_index.md").exists()])

        if only_register:
            register_dirs = [d for d in register_dirs if d.name == only_register]
            if not register_dirs:
                raise CommandError(f"Register '{only_register}' not found")

        self.stdout.write(f"\n📂 Codex: {codex_root}")
        self.stdout.write(f"🗂  Registers to populate: {[d.name for d in register_dirs]}\n")

        total_written = 0

        for reg_dir in register_dirs:
            index_path = reg_dir / "_index.md"
            raw = index_path.read_text(encoding="utf-8")

            # Parse frontmatter
            fm = {}
            fm_match = re.match(r"^---\n(.*?)\n---", raw, re.DOTALL)
            if fm_match:
                try:
                    fm = yaml.safe_load(fm_match.group(1)) or {}
                except Exception:
                    pass

            register_slug = reg_dir.name
            _singular_map = {
                "recipes": "recipe", "people": "person", "purveyors": "purveyor",
                "partners": "partner", "tasks": "task", "notes": "note",
            }
            entity_type = fm.get("entity_type") or _singular_map.get(register_slug) or register_slug.rstrip("s")
            entity_plural = fm.get("display_name") or register_slug.title()
            source_file = fm.get("source_file") or ""

            self.stdout.write(f"── {register_slug} ({entity_plural}) ──────────────")
            self.stdout.write(f"   source: {source_file}")

            if not source_file:
                self.stdout.write(self.style.WARNING("   ⚠  No source_file in _index.md — skipping"))
                continue

            # Find source files on disk — may be multiple (comma-separated)
            source_filenames = [s.strip() for s in source_file.split(",") if s.strip()]
            all_entities: list[dict] = []

            for sfname in source_filenames:
                # Search parse_jobs dirs for this file
                parse_jobs_root = Path(settings.CATALYST_CODEX_ROOT) / "parse_jobs"
                candidates = list(parse_jobs_root.glob(f"*/{sfname}")) if parse_jobs_root.exists() else []

                if not candidates:
                    self.stdout.write(self.style.WARNING(f"   ⚠  {sfname} not found in parse_jobs — skipping"))
                    continue

                # Use the most recently modified copy
                file_path = max(candidates, key=lambda p: p.stat().st_mtime)
                data = file_path.read_bytes()
                self.stdout.write(f"   🔍 Extracting {entity_plural} from {sfname} ({len(data)//1024}KB) …")

                entities = extract_entities(
                    sfname,
                    data,
                    entity_type=entity_type,
                    entity_plural=entity_plural,
                    client_context=client_context,
                    timeout=timeout,
                )
                self.stdout.write(f"       → {len(entities)} {entity_plural} found")
                all_entities.extend(entities)

            if not all_entities:
                self.stdout.write(self.style.WARNING(f"   ⚠  No entities extracted for {register_slug}"))
                continue

            if dry_run:
                for e in all_entities[:5]:
                    self.stdout.write(f"   • {e.get('name', '?')} — {list(e.keys())}")
                if len(all_entities) > 5:
                    self.stdout.write(f"   … and {len(all_entities) - 5} more")
                continue

            # Write entity files
            seen_slugs: set = set()
            extracted_at = NOW_ISO()
            written_count = 0

            for entity in all_entities:
                name = entity.get("name", "").strip()
                if not name:
                    continue

                slug = _unique_slug(_slugify(name), seen_slugs)
                entity_path = reg_dir / f"{slug}.md"

                # Build extra frontmatter from remaining fields
                extra = {k: v for k, v in entity.items() if k != "name" and v}
                extra_lines = "".join(f"{k}: {v}\n" for k, v in extra.items())

                # Build body from extra fields as readable prose
                body_lines = [f"**{k.replace('_', ' ').title()}:** {v}" for k, v in extra.items()]
                body = "\n\n".join(body_lines) if body_lines else ""

                entity_path.write_text(
                    ENTITY_TEMPLATE.format(
                        entry_id=str(uuid.uuid4()),
                        name=name,
                        register_slug=register_slug,
                        source_file=sfname if len(source_filenames) == 1 else source_file,
                        extracted_at=extracted_at,
                        extra_fields=extra_lines,
                        body=body,
                    ),
                    encoding="utf-8",
                )
                written_count += 1

            self.stdout.write(self.style.SUCCESS(f"   ✅ {written_count} entity files written to {reg_dir.name}/"))
            total_written += written_count

        if dry_run or total_written == 0:
            if not dry_run:
                self.stdout.write(self.style.WARNING("\nNothing written."))
            return

        # Commit everything
        _git(codex_root, "add", "CONTENT/registers/")
        commit_msg = f"ingest: populate {total_written} entity entries across {len(register_dirs)} register(s)"
        _git(codex_root, "commit", "-m", commit_msg)
        commit_hash = _git(codex_root, "rev-parse", "--short", "HEAD")

        self.stdout.write(self.style.SUCCESS(
            f"\n✅ {total_written} entity files committed to Codex [{commit_hash}]\n"
        ))
