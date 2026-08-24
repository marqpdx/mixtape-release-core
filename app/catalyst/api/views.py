# catalyst/api/views.py
"""
Catalyst Codex API — file materialization, browse, and async parse endpoints.

POST /api/catalyst/groups/{slug}/parse-files/
  Phase 1 — structural parse only (fast, no AI). Returns shape proposals
  aligned against client vocabulary, creates a CatalystParseJob, stores
  uploaded files on disk for Phase 2.

POST /api/catalyst/groups/{slug}/parse-jobs/{job_id}/start-analysis/
  Phase 2 — enqueue per-file Celery semantic-analysis tasks. Client calls
  this after confirming Phase 1 shape and optionally adding enrichment context.

GET  /api/catalyst/groups/{slug}/parse-jobs/{job_id}/status/
  Returns current job status and, when complete, merged_registers.

POST /api/catalyst/groups/{slug}/materialize-registers/
  Writes CONTENT/registers/{register_slug}/_index.md for each confirmed register.

GET  /api/catalyst/groups/{slug}/registers/
  Lists all materialized registers for the group's Codex.

GET  /api/catalyst/groups/{slug}/registers/{register_slug}/
  Returns frontmatter + body markdown for a single register _index.md.

PATCH /api/catalyst/groups/{slug}/registers/{register_slug}/
  Updates body markdown and/or canonizes the register (status → canon).
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


# ── Shared helpers ─────────────────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)", re.DOTALL)


def _parse_index(path: Path) -> tuple[dict, str]:
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


def _title_from_body(index_path: Path) -> str:
    _, body = _parse_index(index_path)
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return index_path.parent.name


# ── Phase 1 — Structural Parse ────────────────────────────────────────────────

class ParseFilesView(APIView):
    """
    POST /api/catalyst/groups/{slug}/parse-files/

    Phase 1: structural parse only — pure Python, no AI subprocess.
    Runs in < 2s per file. Returns shape proposals aligned against client
    vocabulary (aligned / unexpected / absent). Creates a CatalystParseJob
    and stores uploaded file bytes on disk for Phase 2.

    Response:
      {
        "job_id": "uuid",
        "phase1_results": {
          "aligned":   [...registers that match declared vocabulary...],
          "unexpected":[...registers not in declared vocabulary...],
          "absent":    [...declared types with no matching file...],
          "declared_types": ["recipe", "purveyors", ...]
        },
        "files": [...per-file structural summary...],
        "files_processed": 8,
        "errors": []
      }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, slug):
        group = get_object_or_404(Group, slug=slug, deleted_at__isnull=True)
        if not _is_group_admin(request.user, group):
            return Response({"detail": "Admin access required."}, status=status.HTTP_403_FORBIDDEN)

        from catalyst.services.parse_service import parse_file, align_vocabulary
        from catalyst.models import CatalystParseJob

        uploaded = request.FILES.getlist("files")
        if not uploaded:
            return Response({"detail": "No files uploaded."}, status=status.HTTP_400_BAD_REQUEST)

        general_context = (request.data.get("general_context") or "").strip()
        entity_expectations = (request.data.get("entity_expectations") or "").strip()

        client_context: str = ""
        if general_context or entity_expectations:
            parts = []
            if general_context:
                parts.append(f"ABOUT THESE FILES:\n{general_context}")
            if entity_expectations:
                parts.append(
                    f"ENTITY VOCABULARY (client-defined — these definitions override general assumptions):\n{entity_expectations}"
                )
            client_context = "\n\n".join(parts)
            logger.info("[catalyst] client_context set (%d chars)", len(client_context))

        errors: list[dict] = []
        parsed_files: list[dict] = []
        all_registers: list[dict] = []
        file_meta: list[dict] = []

        # Deduplicate uploaded files by content hash — identical files (e.g. backup copies
        # like "Menu Meeting 6_19-2.docx") would otherwise inflate all entity counts.
        import hashlib
        seen_hashes: set[str] = set()
        deduped_uploads: list[tuple[str, bytes]] = []
        skipped_duplicates: list[str] = []
        for f in uploaded:
            name = f.name
            data = f.read()
            file_hash = hashlib.sha256(data).hexdigest()
            if file_hash in seen_hashes:
                skipped_duplicates.append(name)
                logger.info("[catalyst] skipping duplicate file: %s (same content as earlier upload)", name)
            else:
                seen_hashes.add(file_hash)
                deduped_uploads.append((name, data))

        # Read bytes in main thread; run parse_file() sequentially (fast)
        for name, data in deduped_uploads:
            try:
                result = parse_file(name, data)
                registers_dicts = [
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
                    "registers": registers_dicts,
                    "skipped": result.skipped,
                    "file_notes": result.file_notes,
                })
                all_registers.extend(registers_dicts)
                file_meta.append({
                    "filename": name,
                    "size_bytes": len(data),
                    "file_type": result.file_type,
                    "_data": data,  # held in memory until stored to disk below
                })
            except Exception as exc:
                logger.exception("[catalyst] parse_file failed for %s", name)
                errors.append({"file": name, "error": str(exc)})

        # Vocabulary alignment — pass general_context so vertical shape children
        # can be detected and nested types are not incorrectly marked absent
        phase1 = align_vocabulary(entity_expectations, all_registers, general_context=general_context) if entity_expectations else {
            "aligned": all_registers,
            "unexpected": [],
            "absent": [],
            "nested_in_parent": [],
            "declared_types": [],
        }

        # Create the job record
        job = CatalystParseJob.objects.create(
            group=group,
            status=CatalystParseJob.STATUS_PHASE1_COMPLETE,
            uploaded_files=[
                {"filename": m["filename"], "size_bytes": m["size_bytes"], "file_type": m["file_type"]}
                for m in file_meta
            ],
            client_context=client_context,
            phase1_results=phase1,
            created_by=request.user,
        )

        # Store raw file bytes on disk for Phase 2 tasks
        job_dir = job.job_dir()
        job_dir.mkdir(parents=True, exist_ok=True)
        for m in file_meta:
            dest = job_dir / m["filename"]
            dest.write_bytes(m["_data"])

        logger.info(
            "[catalyst] Phase 1 complete — job=%s group=%s files=%d aligned=%d unexpected=%d absent=%d",
            job.id, slug, len(file_meta),
            len(phase1["aligned"]), len(phase1["unexpected"]), len(phase1["absent"]),
        )

        return Response({
            "job_id": str(job.id),
            "phase1_results": phase1,
            "files": parsed_files,
            "files_processed": len(deduped_uploads),
            "skipped_duplicates": skipped_duplicates,
            "errors": errors,
        }, status=status.HTTP_200_OK)


# ── Phase 2 — Start Async Analysis ────────────────────────────────────────────

class StartAnalysisView(APIView):
    """
    POST /api/catalyst/groups/{slug}/parse-jobs/{job_id}/start-analysis/

    Body (optional): {"enrichment_context": "...additional context..."}

    Appends enrichment_context to client_context, enqueues one
    run_file_semantic_analysis task per uploaded file, sets status → analyzing.

    Response: {"job_id": "...", "status": "analyzing", "files_queued": N}
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, slug, job_id):
        group = get_object_or_404(Group, slug=slug, deleted_at__isnull=True)
        if not _is_group_admin(request.user, group):
            return Response({"detail": "Admin access required."}, status=status.HTTP_403_FORBIDDEN)

        from catalyst.models import CatalystParseJob
        from catalyst.tasks import run_file_semantic_analysis

        try:
            job = CatalystParseJob.objects.get(pk=job_id, group=group)
        except CatalystParseJob.DoesNotExist:
            return Response({"detail": "Job not found."}, status=status.HTTP_404_NOT_FOUND)

        if job.status == CatalystParseJob.STATUS_ANALYZING:
            return Response({"detail": "Analysis already in progress."}, status=status.HTTP_409_CONFLICT)
        if job.status == CatalystParseJob.STATUS_COMPLETE:
            return Response({"detail": "Analysis already complete."}, status=status.HTTP_409_CONFLICT)

        enrichment = (request.data.get("enrichment_context") or "").strip()
        if enrichment:
            sep = "\n\n" if job.client_context else ""
            job.client_context = job.client_context + sep + f"ADDITIONAL CONTEXT (added after Phase 1 review):\n{enrichment}"

        job.status = CatalystParseJob.STATUS_ANALYZING
        job.save(update_fields=["status", "client_context"])

        # Enqueue one task per file
        files_queued = 0
        for file_entry in job.uploaded_files:
            filename = file_entry["filename"]
            run_file_semantic_analysis.apply_async(
                args=[str(job.id), filename],
                queue="catalyst",
            )
            files_queued += 1

        logger.info("[catalyst] Phase 2 started — job=%s files_queued=%d", job.id, files_queued)

        return Response({
            "job_id": str(job.id),
            "status": job.status,
            "files_queued": files_queued,
        }, status=status.HTTP_200_OK)


# ── Job Status ────────────────────────────────────────────────────────────────

class ParseJobStatusView(APIView):
    """
    GET /api/catalyst/groups/{slug}/parse-jobs/{job_id}/status/

    Returns current job status. When complete, includes merged_registers.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, slug, job_id):
        group = get_object_or_404(Group, slug=slug, deleted_at__isnull=True)
        if not _is_group_admin(request.user, group):
            return Response({"detail": "Admin access required."}, status=status.HTTP_403_FORBIDDEN)

        from catalyst.models import CatalystParseJob

        try:
            job = CatalystParseJob.objects.get(pk=job_id, group=group)
        except CatalystParseJob.DoesNotExist:
            return Response({"detail": "Job not found."}, status=status.HTTP_404_NOT_FOUND)

        files_done = len(job.phase2_results.get("files", {}))
        files_total = len(job.uploaded_files)

        resp: dict = {
            "job_id": str(job.id),
            "status": job.status,
            "files_done": files_done,
            "files_total": files_total,
        }

        if job.status == CatalystParseJob.STATUS_COMPLETE:
            resp["merged_registers"] = job.phase2_results.get("merged_registers", [])
            resp["completed_at"] = job.completed_at.isoformat() if job.completed_at else None

        return Response(resp, status=status.HTTP_200_OK)


# ── Materialize Registers ─────────────────────────────────────────────────────

class MaterializeRegistersView(APIView):
    """
    POST /api/catalyst/groups/{slug}/materialize-registers/
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
            return Response({"detail": "No registers provided."}, status=status.HTTP_400_BAD_REQUEST)

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
            return Response({"detail": "No valid registers to write."}, status=status.HTTP_400_BAD_REQUEST)

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


# ── List / Detail / Edit Registers ────────────────────────────────────────────

class ListRegistersView(APIView):
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


class RegisterDetailView(APIView):
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


class RegisterMaterializeView(APIView):
    """
    POST /api/catalyst/groups/{slug}/registers/{register_slug}/materialize/

    Body: {"job_id": "<uuid>"}

    Queues a Celery task that runs extract_entities_chunked() against the
    register's source files and writes the results into the register _index.md.
    Returns immediately — the task runs asynchronously.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, slug, register_slug):
        from catalyst.models import CatalystParseJob
        from catalyst.tasks import materialize_register_entities

        group = get_object_or_404(Group, slug=slug, deleted_at__isnull=True)
        if not _is_group_admin(request.user, group):
            return Response(
                {"detail": "Admin access required."},
                status=status.HTTP_403_FORBIDDEN,
            )

        job_id = request.data.get("job_id")
        if not job_id:
            # Fall back: find the latest completed job for this group
            job = (
                CatalystParseJob.objects
                .filter(group=group, status=CatalystParseJob.STATUS_COMPLETE)
                .order_by("-completed_at")
                .first()
            )
            if not job:
                return Response(
                    {"detail": "No completed parse job found for this group. Run Phase 2 first."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            job_id = str(job.pk)
        else:
            try:
                CatalystParseJob.objects.get(pk=job_id, group=group)
            except CatalystParseJob.DoesNotExist:
                return Response(
                    {"detail": "Parse job not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        index_path = _codex_root(slug) / "CONTENT" / "registers" / register_slug / "_index.md"
        if not index_path.exists():
            return Response(
                {"detail": f"Register '{register_slug}' not found. Confirm registers first."},
                status=status.HTTP_404_NOT_FOUND,
            )

        materialize_register_entities.apply_async(
            args=[slug, register_slug, str(job_id)],
            queue="catalyst",
        )
        logger.info(
            "[catalyst] materialize queued: group=%s register=%s job=%s by %s",
            slug, register_slug, job_id, request.user.username,
        )
        return Response({"status": "queued", "register": register_slug, "job_id": str(job_id)})
