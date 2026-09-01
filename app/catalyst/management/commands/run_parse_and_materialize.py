"""
management command: run_parse_and_materialize

Runs semantic_analyze() sequentially on all files in a CatalystParseJob,
then materializes the resulting registers directly into the Codex.

Usage:
  python manage.py run_parse_and_materialize <job_id> [--slug <group-slug>] [--timeout 210] [--dry-run]

If --slug is omitted, the group slug is read from the job record.
"""

import logging
import uuid
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run semantic analysis on a parse job and materialize registers into Codex"

    def add_arguments(self, parser):
        parser.add_argument("job_id", type=str)
        parser.add_argument("--slug", type=str, default=None)
        parser.add_argument("--timeout", type=int, default=210)
        parser.add_argument("--dry-run", action="store_true", help="Print results without writing to Codex")

    def handle(self, *args, **options):
        from catalyst.models import CatalystParseJob
        from catalyst.services.parse_service import register_slug_for_entity, semantic_analyze, slugify
        from catalyst.api.views import (
            _bootstrap_codex, _git, REGISTER_INDEX_TEMPLATE, NOW_ISO,
        )
        from groups.models.group import Group

        job_id = options["job_id"]
        timeout = options["timeout"]
        dry_run = options["dry_run"]

        try:
            job = CatalystParseJob.objects.select_related("group").get(pk=job_id)
        except CatalystParseJob.DoesNotExist:
            raise CommandError(f"Job {job_id} not found")

        group = job.group
        slug = options["slug"] or group.slug
        job_dir = job.job_dir()

        self.stdout.write(f"\n📂 Job: {job_id}")
        self.stdout.write(f"📍 Group: {slug}")
        self.stdout.write(f"📁 Files dir: {job_dir}")
        self.stdout.write(f"⏱  Subprocess timeout: {timeout}s\n")

        if not job_dir.exists():
            raise CommandError(f"Job directory not found: {job_dir}")

        files = [f["filename"] for f in (job.uploaded_files or []) if f.get("filename")]
        if not files:
            raise CommandError("No files recorded in job.uploaded_files")

        # ── Phase 2: sequential semantic analysis ──────────────────────────────
        results = {}
        for filename in files:
            file_path = job_dir / filename
            if not file_path.exists():
                self.stdout.write(self.style.WARNING(f"  ⚠  {filename} — not found on disk, skipping"))
                continue

            data = file_path.read_bytes()
            self.stdout.write(f"  🔍 Analyzing: {filename} ({len(data)//1024}KB) …")

            ai = semantic_analyze(
                filename,
                data,
                codex_cwd=None,
                client_context=job.client_context or None,
                timeout=timeout,
            )

            if ai is None:
                self.stdout.write(self.style.WARNING(f"       → skipped (empty or unreadable)"))
                results[filename] = {"count": 0}
                continue

            count = ai.get("count", 0)
            entity = ai.get("entity_plural") or ai.get("entity_type", "records")
            conf = ai.get("confidence", "?")
            self.stdout.write(self.style.SUCCESS(
                f"       → {count} {entity} (confidence: {conf})"
            ))
            results[filename] = ai

        # ── Merge registers ────────────────────────────────────────────────────
        merged: dict[str, dict] = {}
        for filename, ai in results.items():
            if not ai or ai.get("count", 0) == 0:
                continue
            ai_slug = register_slug_for_entity(ai.get("entity_type"), ai.get("entity_plural"))
            ai_notes = f"e.g. {', '.join(ai['examples'][:3])}" if ai.get("examples") else ""
            if ai_slug in merged:
                merged[ai_slug]["entry_count"] += ai["count"]
                if filename not in merged[ai_slug]["source_file"]:
                    merged[ai_slug]["source_file"] += f", {filename}"
                if ai_notes:
                    merged[ai_slug]["notes"] += f"; {ai_notes}"
            else:
                merged[ai_slug] = {
                    "slug": ai_slug,
                    "display_name": (ai.get("entity_plural") or ai.get("entity_type", "records")).title(),
                    "entry_count": ai["count"],
                    "source_file": filename,
                    "canon_synonym": "Canon",
                    "notes": ai_notes,
                    "confidence": ai.get("confidence", "medium"),
                }

        self.stdout.write(f"\n📋 Merged registers ({len(merged)}):")
        for r in merged.values():
            self.stdout.write(f"   • {r['entry_count']} {r['display_name']} [{r['slug']}] from {r['source_file']}")

        if not merged:
            raise CommandError("No entities found across all files — nothing to materialize.")

        if dry_run:
            self.stdout.write(self.style.WARNING("\n--dry-run: skipping Codex write."))
            return

        # ── Materialize into Codex ─────────────────────────────────────────────
        codex_root = Path(settings.CATALYST_CODEX_ROOT) / slug
        self.stdout.write(f"\n📝 Writing to Codex: {codex_root}")

        _bootstrap_codex(codex_root, slug)
        registers_dir = codex_root / "CONTENT" / "registers"
        registers_dir.mkdir(parents=True, exist_ok=True)

        created_at = NOW_ISO()
        written = []

        for reg in merged.values():
            reg_dir = registers_dir / reg["slug"]
            reg_dir.mkdir(exist_ok=True)
            index_path = reg_dir / "_index.md"
            index_path.write_text(
                REGISTER_INDEX_TEMPLATE.format(
                    entry_id=str(uuid.uuid4()),
                    display_name=reg["display_name"],
                    canon_synonym=reg["canon_synonym"],
                    entry_count=reg["entry_count"],
                    source_file=reg["source_file"],
                    confirmed_by="catalyst-session",
                    created_at=created_at,
                ),
                encoding="utf-8",
            )
            written.append(str(index_path.relative_to(codex_root)))
            self.stdout.write(self.style.SUCCESS(f"   ✅ {reg['slug']}/_index.md written"))

        _git(codex_root, "add", "CONTENT/registers/")
        commit_msg = f"ingest: materialize {len(written)} register(s) — session run at {created_at}"
        _git(codex_root, "commit", "-m", commit_msg)
        commit_hash = _git(codex_root, "rev-parse", "--short", "HEAD")

        self.stdout.write(self.style.SUCCESS(
            f"\n✅ Done — {len(written)} registers committed to Codex [{commit_hash}]\n"
        ))
