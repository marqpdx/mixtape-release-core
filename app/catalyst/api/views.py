# catalyst/api/views.py
"""
Catalyst Codex API — file materialization and browse endpoints.

POST /api/catalyst/groups/{slug}/materialize-registers/
  Writes CONTENT/registers/{register_slug}/_index.md for each confirmed register.

GET  /api/catalyst/groups/{slug}/registers/
  Lists all materialized registers for the group's Codex.

GET  /api/catalyst/groups/{slug}/registers/{register_slug}/
  Returns frontmatter + body markdown for a single register _index.md.

PATCH /api/catalyst/groups/{slug}/registers/{register_slug}/
  Updates body markdown and/or canonizes the register (status → canon).

POST /api/catalyst/groups/{slug}/parse-files/
  Accepts multipart file uploads; returns proposed register shapes (Stage 3).
"""

import logging
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

from django.conf import settings
from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from groups.models.group import Group
from groups.models import GroupMembership
from django.contrib.contenttypes.models import ContentType

logger = logging.getLogger(__name__)

NOW_ISO = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731

REGISTER_INDEX_TEMPLATE = """\
---
id: "{entry_id}"
pattern_type: register
movement: structural
stakes_tier: standard
change_class: null
status: pre-canon
canon_synonym: "{canon_synonym}"
suggestion_level: null
provenance:
  created_by: "catalyst-ingest"
  created_at: "{created_at}"
  confirmed_by: "{confirmed_by}"
  confirmed_at: "{created_at}"
  commit: null
source_file: "{source_file}"
entry_count: {entry_count}
cross_references: []
---

# {display_name}

**Purpose:** Imported from `{source_file}` via Catalyst ingest. {entry_count} entries pending materialization.

**Canon synonym:** {canon_synonym} — the label used for a confirmed, authoritative entry in this register.

## Entries

<!-- entries materialized here after Stage 5 parse endpoint is live -->
"""


def _git(codex_root: Path, *args) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=codex_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _bootstrap_codex(codex_root: Path, group_slug: str) -> bool:
    """
    Ensure the Codex directory exists with a git repo and CONTENT skeleton.
    Returns True if bootstrapped fresh, False if already existed.
    """
    if codex_root.exists() and (codex_root / ".git").exists():
        return False

    codex_root.mkdir(parents=True, exist_ok=True)
    _git(codex_root, "init")
    _git(codex_root, "config", "user.name", "Catalyst Ingest")
    _git(codex_root, "config", "user.email", "catalyst@crossroads.place")

    (codex_root / "CONTENT").mkdir(exist_ok=True)
    (codex_root / "CONTENT" / "registers").mkdir(exist_ok=True)
    (codex_root / ".catalyst").mkdir(exist_ok=True)

    readme = codex_root / "CONTENT" / "README.md"
    readme.write_text(
        f"# {group_slug} Codex\n\nBootstrapped by Catalyst ingest — {NOW_ISO()}\n"
    )
    _git(codex_root, "add", ".")
    _git(codex_root, "commit", "-m", f"bootstrap: Codex skeleton for {group_slug}")
    return True


def _is_group_admin(user, group) -> bool:
    from django.contrib.auth import get_user_model
    User = get_user_model()
    user_ct = ContentType.objects.get_for_model(User)
    return GroupMembership.objects.filter(
        group=group,
        member_content_type=user_ct,
        member_object_id=user.pk,
        is_active=True,
        roles__overlap=["owner", "admin", "steward"],
    ).exists()


class MaterializeRegistersView(APIView):
    """
    POST /api/catalyst/groups/{slug}/materialize-registers/

    Body:
      {
        "registers": [
          {
            "slug": "meals",
            "display_name": "Meal Register",
            "canon_synonym": "Final Menu",
            "entry_count": 16,
            "source_file": "2026_Temple_Menu. UPDATED.docx"
          },
          ...
        ]
      }

    Response:
      {
        "codex_root": "/abs/path",
        "bootstrapped": true,
        "registers_written": 7,
        "commit": "abc1234",
        "files": ["CONTENT/registers/meals/_index.md", ...]
      }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, slug):
        group = get_object_or_404(Group, slug=slug, deleted_at__isnull=True)

        if not _is_group_admin(request.user, group):
            return Response(
                {"detail": "You must be an owner, admin, or steward to materialize registers."},
                status=status.HTTP_403_FORBIDDEN,
            )

        registers = request.data.get("registers", [])
        if not registers:
            return Response(
                {"detail": "No registers provided."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        codex_root = Path(settings.CATALYST_CODEX_ROOT) / slug
        try:
            bootstrapped = _bootstrap_codex(codex_root, slug)
        except Exception as exc:
            logger.exception("Codex bootstrap failed for %s", slug)
            return Response(
                {"detail": f"Codex bootstrap failed: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        registers_dir = codex_root / "CONTENT" / "registers"
        registers_dir.mkdir(parents=True, exist_ok=True)

        written_files = []
        confirmed_by = request.user.username
        created_at = NOW_ISO()

        for reg in registers:
            reg_slug = reg.get("slug", "")
            display_name = reg.get("display_name") or reg.get("displayName") or reg_slug
            canon_synonym = reg.get("canon_synonym") or reg.get("canonSynonym") or "Canonized"
            entry_count = reg.get("entry_count") or reg.get("entryCount") or 0
            source_file = reg.get("source_file") or reg.get("sourceFile") or ""

            if not reg_slug:
                continue

            reg_dir = registers_dir / reg_slug
            reg_dir.mkdir(exist_ok=True)

            index_path = reg_dir / "_index.md"
            index_path.write_text(
                REGISTER_INDEX_TEMPLATE.format(
                    entry_id=str(uuid.uuid4()),
                    display_name=display_name,
                    canon_synonym=canon_synonym,
                    entry_count=entry_count,
                    source_file=source_file,
                    confirmed_by=confirmed_by,
                    created_at=created_at,
                ),
                encoding="utf-8",
            )
            rel = str(index_path.relative_to(codex_root))
            written_files.append(rel)

        if not written_files:
            return Response(
                {"detail": "No valid registers to write."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            _git(codex_root, "add", "CONTENT/registers/")
            commit_msg = (
                f"ingest: materialize {len(written_files)} register(s) — "
                f"confirmed by {confirmed_by} at {created_at}"
            )
            _git(codex_root, "commit", "-m", commit_msg)
            commit_hash = _git(codex_root, "rev-parse", "--short", "HEAD")
        except Exception as exc:
            logger.exception("git commit failed for %s", slug)
            return Response(
                {"detail": f"Files written but git commit failed: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "codex_root": str(codex_root),
                "bootstrapped": bootstrapped,
                "registers_written": len(written_files),
                "commit": commit_hash,
                "files": written_files,
            },
            status=status.HTTP_201_CREATED,
        )


# ── Shared helpers ─────────────────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)", re.DOTALL)


def _parse_index(path: Path) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_markdown) from a _index.md file."""
    raw = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        return {}, raw
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    return fm, m.group(2).strip()


def _write_index(path: Path, fm: dict, body: str) -> None:
    fm_str = yaml.dump(fm, default_flow_style=False, allow_unicode=True).strip()
    path.write_text(f"---\n{fm_str}\n---\n\n{body}\n", encoding="utf-8")


def _codex_root(slug: str) -> Path:
    return Path(settings.CATALYST_CODEX_ROOT) / slug


class ListRegistersView(APIView):
    """
    GET /api/catalyst/groups/{slug}/registers/
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, slug):
        group = get_object_or_404(Group, slug=slug, deleted_at__isnull=True)
        if not _is_group_admin(request.user, group):
            return Response({"detail": "Admin access required."}, status=status.HTTP_403_FORBIDDEN)

        registers_dir = _codex_root(slug) / "CONTENT" / "registers"
        if not registers_dir.exists():
            return Response([], status=status.HTTP_200_OK)

        results = []
        for reg_dir in sorted(registers_dir.iterdir()):
            if not reg_dir.is_dir():
                continue
            index = reg_dir / "_index.md"
            if not index.exists():
                continue
            fm, _ = _parse_index(index)
            results.append({
                "slug": reg_dir.name,
                "display_name": fm.get("id", reg_dir.name),
                "title": _title_from_body(index),
                "canon_synonym": fm.get("canon_synonym", ""),
                "entry_count": fm.get("entry_count", 0),
                "status": fm.get("status", "pre-canon"),
                "source_file": fm.get("source_file", ""),
            })

        return Response(results)


def _title_from_body(index_path: Path) -> str:
    _, body = _parse_index(index_path)
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return index_path.parent.name


class RegisterDetailView(APIView):
    """
    GET  /api/catalyst/groups/{slug}/registers/{register_slug}/
    PATCH /api/catalyst/groups/{slug}/registers/{register_slug}/
    """

    permission_classes = [IsAuthenticated]

    def _get_index(self, slug, register_slug):
        path = _codex_root(slug) / "CONTENT" / "registers" / register_slug / "_index.md"
        if not path.exists():
            return None, None, None
        fm, body = _parse_index(path)
        return path, fm, body

    def get(self, request, slug, register_slug):
        group = get_object_or_404(Group, slug=slug, deleted_at__isnull=True)
        if not _is_group_admin(request.user, group):
            return Response({"detail": "Admin access required."}, status=status.HTTP_403_FORBIDDEN)

        path, fm, body = self._get_index(slug, register_slug)
        if path is None:
            return Response({"detail": "Register not found."}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            "slug": register_slug,
            "frontmatter": fm,
            "body_markdown": body,
            "canon_synonym": fm.get("canon_synonym", ""),
            "entry_count": fm.get("entry_count", 0),
            "status": fm.get("status", "pre-canon"),
        })

    def patch(self, request, slug, register_slug):
        group = get_object_or_404(Group, slug=slug, deleted_at__isnull=True)
        if not _is_group_admin(request.user, group):
            return Response({"detail": "Admin access required."}, status=status.HTTP_403_FORBIDDEN)

        path, fm, body = self._get_index(slug, register_slug)
        if path is None:
            return Response({"detail": "Register not found."}, status=status.HTTP_404_NOT_FOUND)

        new_body = request.data.get("body_markdown", body)
        canonize = request.data.get("canonize", False)
        new_synonym = request.data.get("canon_synonym")
        new_display_name = request.data.get("display_name")
        decanonize = request.data.get("decanonize", False)

        changed_fields = []

        if canonize:
            fm["status"] = "canon"
            if "provenance" not in fm:
                fm["provenance"] = {}
            fm["provenance"]["canonized_by"] = request.user.username
            fm["provenance"]["canonized_at"] = NOW_ISO()
            changed_fields.append("canonize")

        if decanonize:
            fm["status"] = "pre-canon"
            changed_fields.append("decanonize")

        if new_synonym is not None:
            fm["canon_synonym"] = new_synonym
            changed_fields.append("synonym")

        if new_display_name is not None:
            fm["display_name"] = new_display_name
            changed_fields.append("display_name")

        codex_root = _codex_root(slug)
        _write_index(path, fm, new_body)

        try:
            rel = str(path.relative_to(codex_root))
            _git(codex_root, "add", rel)
            verb = ", ".join(changed_fields) if changed_fields else "edit"
            _git(codex_root, "commit", "-m",
                 f"{verb}: {register_slug} — by {request.user.username} at {NOW_ISO()}")
            commit_hash = _git(codex_root, "rev-parse", "--short", "HEAD")
        except Exception as exc:
            logger.exception("git commit failed for register %s/%s", slug, register_slug)
            return Response({"detail": f"File written but git commit failed: {exc}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            "slug": register_slug,
            "status": fm.get("status"),
            "canon_synonym": fm.get("canon_synonym", ""),
            "display_name": fm.get("display_name", register_slug),
            "commit": commit_hash,
            "canonized": canonize,
        })


class ParseFilesView(APIView):
    """
    POST /api/catalyst/groups/{slug}/parse-files/

    Multipart form upload — one or more files under the key "files".
    Returns proposed register shapes derived from file structure (Stage 3).

    Response:
      {
        "proposed_registers": [
          {
            "slug": "meals",
            "display_name": "Meal Register",
            "entry_count": 16,
            "source_file": "2026_Temple_Menu.docx",
            "canon_synonym": "Canon",
            "notes": ""
          },
          ...
        ],
        "files_processed": 2,
        "errors": []
      }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, slug):
        group = get_object_or_404(Group, slug=slug, deleted_at__isnull=True)
        if not _is_group_admin(request.user, group):
            return Response({"detail": "Admin access required."}, status=status.HTTP_403_FORBIDDEN)

        from catalyst.services.parse_service import parse_file

        uploaded = request.FILES.getlist("files")
        if not uploaded:
            return Response({"detail": "No files uploaded."}, status=status.HTTP_400_BAD_REQUEST)

        _conf_rank = {"high": 2, "medium": 1, "low": 0}

        errors = []
        parsed_files = []
        merged: dict[str, dict] = {}  # slug → best accumulated register dict

        for f in uploaded:
            try:
                result = parse_file(f.name, f.read())

                file_registers = [
                    {
                        "slug": r.slug,
                        "display_name": r.display_name,
                        "entry_count": r.entry_count,
                        "source_file": r.source_file,
                        "canon_synonym": r.canon_synonym,
                        "notes": r.notes,
                        "confidence": r.confidence,
                        "columns": r.columns,
                    }
                    for r in result.registers
                ]

                parsed_files.append({
                    "filename": result.filename,
                    "file_type": result.file_type,
                    "registers": file_registers,
                    "skipped": result.skipped,
                    "file_notes": result.file_notes,
                })

                for r in result.registers:
                    if r.slug in merged:
                        merged[r.slug]["entry_count"] += r.entry_count
                        if r.source_file not in merged[r.slug]["source_file"]:
                            merged[r.slug]["source_file"] += f", {r.source_file}"
                        if r.notes:
                            merged[r.slug]["notes"] += f"; {r.notes}"
                        # keep highest confidence
                        if _conf_rank.get(r.confidence, 1) > _conf_rank.get(merged[r.slug]["confidence"], 1):
                            merged[r.slug]["confidence"] = r.confidence
                            merged[r.slug]["columns"] = r.columns
                    else:
                        merged[r.slug] = {
                            "slug": r.slug,
                            "display_name": r.display_name,
                            "entry_count": r.entry_count,
                            "source_file": r.source_file,
                            "canon_synonym": r.canon_synonym,
                            "notes": r.notes,
                            "confidence": r.confidence,
                            "columns": r.columns,
                        }
            except Exception as exc:
                logger.exception("parse_file failed for %s", f.name)
                errors.append({"file": f.name, "error": str(exc)})

        return Response({
            "files": parsed_files,
            "merged_registers": list(merged.values()),
            "files_processed": len(uploaded),
            "errors": errors,
        }, status=status.HTTP_200_OK)
