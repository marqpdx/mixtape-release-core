# catalyst/api/views.py
"""
Catalyst Codex API — file materialization endpoints.

POST /api/catalyst/groups/{slug}/materialize-registers/
  Accepts confirmed register shapes from the Stage 4 review UI and writes
  CONTENT/registers/{register_slug}/_index.md for each register into the
  tenant's Codex directory. Does a git commit after writing.

  Bootstraps the Codex directory (git init + CONTENT skeleton) if it does
  not yet exist — allows pilot use before the full activation flow is run.
"""

import logging
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

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
