"""
CatalystActivationService — per-tenant Codex provisioning.

Implements the eight-step activation sequence from catalyst-activation-model.md.
Each step is a discrete method so it can be called independently (e.g. re-stamp
hashes after a CORE update, regenerate START-HERE.md, re-seed IR).

The orchestrator `activate()` calls steps 2–7 in order. Step 1 (Qdrant IR
namespace creation) and Step 8 (activation email) are separate concerns handled
by the caller — the management command and admin action both wire those in.

Filesystem layout:
    {CATALYST_CODEX_ROOT}/{slug}/          ← Codex root, git-tracked
    {CATALYST_CODEX_ROOT}/{slug}/CORE/     ← copied from mixtape-release-catalyst
    {CATALYST_CODEX_ROOT}/{slug}/FIXTURE/  ← copied from mixtape-release-catalyst
    {CATALYST_CODEX_ROOT}/{slug}/CONTENT/  ← client-owned, empty at activation
    {CATALYST_CODEX_ROOT}/{slug}/.catalyst/ ← working records

Seed source: mixtape-release-catalyst repo, resolved via CATALYST_SEED_PATH setting.
"""

import hashlib
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings


class CatalystActivationError(Exception):
    pass


class CatalystActivationService:

    SEED_DIRS = ("CORE", "FIXTURE")

    def __init__(self, prospect):
        self.prospect = prospect
        self.slug = prospect.slug
        self.codex_root = Path(settings.CATALYST_CODEX_ROOT) / self.slug
        self.seed_path = Path(getattr(settings, "CATALYST_SEED_PATH", ""))

    # -------------------------------------------------------------------------
    # Step 2 — git init Codex directory
    # -------------------------------------------------------------------------

    def init_codex(self):
        if self.codex_root.exists():
            raise CatalystActivationError(
                f"Codex directory already exists: {self.codex_root}. "
                "Remove it manually or run steps individually."
            )
        self.codex_root.mkdir(parents=True)
        self._git("init")
        self._git("config", "user.name", "Catalyst Activation")
        self._git("config", "user.email", "catalyst@crossroads.place")
        return str(self.codex_root)

    # -------------------------------------------------------------------------
    # Step 3 — copy CORE + FIXTURE from seed, initial commit
    # -------------------------------------------------------------------------

    def copy_seed_files(self):
        if not self.seed_path or not self.seed_path.exists():
            raise CatalystActivationError(
                f"CATALYST_SEED_PATH is not set or does not exist: '{self.seed_path}'. "
                "Set it in settings to the mixtape-release-catalyst repo root."
            )
        for dir_name in self.SEED_DIRS:
            src = self.seed_path / dir_name
            dst = self.codex_root / dir_name
            if not src.exists():
                raise CatalystActivationError(f"Seed directory missing: {src}")
            shutil.copytree(src, dst)

        # Empty CONTENT and .catalyst directories
        (self.codex_root / "CONTENT").mkdir()
        (self.codex_root / ".catalyst").mkdir()

        self._git("add", ".")
        self._git("commit", "-m", f"activation: seed CORE + FIXTURE for {self.slug}")

    # -------------------------------------------------------------------------
    # Step 4 — stamp manifest.json SHA256 hashes
    # -------------------------------------------------------------------------

    def stamp_manifest_hashes(self):
        manifest_path = self.codex_root / "CORE" / "manifest.json"
        if not manifest_path.exists():
            raise CatalystActivationError(f"manifest.json not found at {manifest_path}")

        text = manifest_path.read_text()
        changed = False

        # Replace any "[sha256]" placeholder with the real hash of the file
        for match in re.finditer(r'"path":\s*"([^"]+)"', text):
            rel_path = match.group(1)
            file_path = self.codex_root / "CORE" / rel_path
            if not file_path.exists():
                continue
            sha = hashlib.sha256(file_path.read_bytes()).hexdigest()
            # Replace the placeholder hash value in the same object block
            placeholder_pattern = (
                r'("path":\s*"' + re.escape(rel_path) + r'"[^}]*"hash":\s*)"(\[sha256\]|[a-f0-9]{64})"'
            )
            replacement = rf'\1"{sha}"'
            new_text, n = re.subn(placeholder_pattern, replacement, text, flags=re.DOTALL)
            if n:
                text = new_text
                changed = True

        if changed:
            manifest_path.write_text(text)
            self._git("add", "CORE/manifest.json")
            self._git("commit", "-m", "activation: stamp manifest.json SHA256 hashes")

    # -------------------------------------------------------------------------
    # Step 5 — stamp FIXTURE provenance frontmatter
    # -------------------------------------------------------------------------

    def stamp_fixture_provenance(self):
        fixture_dir = self.codex_root / "FIXTURE"
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        stamped = []

        for md_file in fixture_dir.rglob("*.md"):
            text = md_file.read_text()
            if not text.startswith("---"):
                continue
            # Replace created_at placeholder or add if missing
            if "created_at:" in text:
                text = re.sub(
                    r"created_at:\s*.*",
                    f"created_at: {now_iso}",
                    text,
                    count=1,
                )
            if "created_by:" in text:
                text = re.sub(
                    r"created_by:\s*.*",
                    "created_by: system-activation",
                    text,
                    count=1,
                )
            md_file.write_text(text)
            stamped.append(str(md_file.relative_to(self.codex_root)))

        if stamped:
            self._git("add", "FIXTURE/")
            self._git("commit", "-m", "activation: stamp FIXTURE provenance")

    # -------------------------------------------------------------------------
    # Step 6 — seed IR
    # Minimal viable indexing: provisions a Stackroom library for the tenant
    # group and indexes all CORE + FIXTURE .md files via ingest_text().
    # Full inception-ingestion pipeline (Chapter registry, envelopes, Winnow)
    # is Phase 3B+ work — not in scope here.
    # -------------------------------------------------------------------------

    def seed_ir(self):
        from inkwell.stackroom_http_client import get_or_create_group_library, ingest_text, StackroomClientError

        group = self.prospect.converted_to_group
        if not group:
            raise CatalystActivationError(
                "prospect.converted_to_group is not set — admin activation must run before seed_ir."
            )

        library_id = get_or_create_group_library(group)

        SKIP_DIRS = {"CONTENT", ".catalyst", ".git"}
        md_files = sorted(
            f for f in self.codex_root.rglob("*.md")
            if not any(part in SKIP_DIRS for part in f.parts)
        )

        indexed = 0
        already_current = 0
        errors = []

        for md_file in md_files:
            rel = str(md_file.relative_to(self.codex_root))
            try:
                result = ingest_text(
                    library_id=library_id,
                    source_path=rel,
                    filename=md_file.name,
                    text=md_file.read_text(encoding="utf-8"),
                )
                if result.get("already_current"):
                    already_current += 1
                else:
                    indexed += 1
            except StackroomClientError as e:
                errors.append(f"{rel}: {e}")

        if errors:
            raise CatalystActivationError(
                f"IR seeding failed for {len(errors)} file(s):\n" + "\n".join(errors)
            )

        total = indexed + already_current
        return {
            "status": "ok",
            "slug": self.slug,
            "library_id": str(library_id),
            "files_indexed": indexed,
            "files_already_current": already_current,
            "message": (
                f"Indexed {indexed} file(s), {already_current} already current "
                f"({total} total) into library {library_id}."
            ),
        }

    # -------------------------------------------------------------------------
    # Step 7 — generate START-HERE.md from docent.template.md
    # -------------------------------------------------------------------------

    def generate_docent(self):
        template_path = self.codex_root / "CORE" / "templates" / "docent.template.md"
        if not template_path.exists():
            raise CatalystActivationError(f"docent.template.md not found at {template_path}")

        template = template_path.read_text()
        now = datetime.now(timezone.utc)
        activation_date = now.strftime("%Y-%m-%d")
        activation_timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Conditional blocks: {{#if field}}...{{/if}}
        def render_if_block(text, field_name, value):
            pattern = r"\{\{#if " + re.escape(field_name) + r"\}\}(.*?)\{\{/if\}\}"
            replacement = value.strip() and re.sub(pattern, r"\1", text, flags=re.DOTALL) or re.sub(pattern, "", text, flags=re.DOTALL)
            return replacement

        rendered = template
        rendered = render_if_block(rendered, "org_description", self.prospect.org_description)
        rendered = render_if_block(rendered, "knowledge_goal", self.prospect.knowledge_goal)

        # Simple variable substitution
        substitutions = {
            "client_slug": self.slug,
            "client_name": self.prospect.name,
            "org_description": self.prospect.org_description,
            "knowledge_goal": self.prospect.knowledge_goal,
            "activation_date": activation_date,
            "activation_timestamp": activation_timestamp,
        }
        for key, value in substitutions.items():
            rendered = rendered.replace("{{" + key + "}}", value)

        output_path = self.codex_root / "START-HERE.md"
        output_path.write_text(rendered)

        self._git("add", "START-HERE.md")
        self._git("commit", "-m", f"activation: generate START-HERE.md for {self.slug}")

        return str(output_path)

    # -------------------------------------------------------------------------
    # Orchestrator — steps 2–7
    # -------------------------------------------------------------------------

    def activate(self):
        results = {}
        results["codex_root"] = self.init_codex()
        self.copy_seed_files()
        self.stamp_manifest_hashes()
        self.stamp_fixture_provenance()
        results["ir"] = self.seed_ir()
        results["docent"] = self.generate_docent()
        return results

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _git(self, *args):
        result = subprocess.run(
            ["git", *args],
            cwd=self.codex_root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise CatalystActivationError(
                f"git {' '.join(args)} failed:\n{result.stderr.strip()}"
            )
        return result.stdout.strip()
