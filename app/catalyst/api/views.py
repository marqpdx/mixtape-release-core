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
import json
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

        from catalyst.services.parse_service import (
            align_vocabulary,
            build_source_section_map,
            build_source_inventory_item,
            build_strategy_map,
            parse_file,
        )
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
        seen_hashes: dict[str, str] = {}
        deduped_uploads: list[tuple[str, bytes, str]] = []
        skipped_duplicates: list[str] = []
        duplicate_groups: dict[str, list[str]] = {}
        text_duplicate_groups: dict[str, list[str]] = {}
        source_inventory: list[dict] = []
        section_maps: dict[str, dict] = {}
        seen_text_hashes: dict[str, str] = {}
        for f in uploaded:
            name = f.name
            data = f.read()
            file_hash = hashlib.sha256(data).hexdigest()
            duplicate_groups.setdefault(file_hash, []).append(name)
            if file_hash in seen_hashes:
                skipped_duplicates.append(name)
                source_inventory.append(
                    build_source_inventory_item(
                        name,
                        data,
                        parsed_file=None,
                        file_hash=file_hash,
                        duplicate_of=seen_hashes[file_hash],
                        general_context=general_context,
                        entity_expectations=entity_expectations,
                    )
                )
                logger.info(
                    "[catalyst] skipping duplicate file: %s (same content as %s)",
                    name,
                    seen_hashes[file_hash],
                )
            else:
                seen_hashes[file_hash] = name
                deduped_uploads.append((name, data, file_hash))

        # Read bytes in main thread; run parse_file() sequentially (fast)
        for name, data, file_hash in deduped_uploads:
            try:
                result = parse_file(name, data)
                inventory_item = build_source_inventory_item(
                    name,
                    data,
                    parsed_file=result,
                    file_hash=file_hash,
                    general_context=general_context,
                    entity_expectations=entity_expectations,
                )
                text_hash = inventory_item.get("text_sha256")
                if text_hash and text_hash in seen_text_hashes:
                    duplicate_of = seen_text_hashes[text_hash]
                    inventory_item["duplicate_of"] = duplicate_of
                    inventory_item["process_decision"] = "skipped_duplicate_text"
                    skipped_duplicates.append(name)
                    text_duplicate_groups.setdefault(text_hash, [duplicate_of]).append(name)
                    source_inventory.append(inventory_item)
                    logger.info(
                        "[catalyst] skipping text duplicate file: %s (normalized text matches %s)",
                        name,
                        duplicate_of,
                    )
                    continue
                if text_hash:
                    seen_text_hashes[text_hash] = name
                    text_duplicate_groups.setdefault(text_hash, [name])
                source_inventory.append(inventory_item)
                section_maps[name] = build_source_section_map(
                    name,
                    data,
                    domain=inventory_item.get("domain"),
                )
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
                source_inventory.append(
                    build_source_inventory_item(
                        name,
                        data,
                        parsed_file=None,
                        file_hash=file_hash,
                        general_context=general_context,
                        entity_expectations=entity_expectations,
                    )
                )
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
        duplicate_group_list = [
            {"sha256": file_hash, "filenames": filenames}
            for file_hash, filenames in duplicate_groups.items()
            if len(filenames) > 1
        ]
        phase1["source_inventory"] = {
            "version": "0.1",
            "files": source_inventory,
            "duplicate_groups": duplicate_group_list,
            "text_duplicate_groups": [
                {"text_sha256": text_hash, "filenames": filenames}
                for text_hash, filenames in text_duplicate_groups.items()
                if len(filenames) > 1
            ],
        }
        phase1["strategy_map"] = build_strategy_map(
            source_inventory,
            general_context=general_context,
            entity_expectations=entity_expectations,
        )
        phase1["section_map"] = {
            "version": "0.1",
            "status": "proposed",
            "files": section_maps,
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
            "source_inventory": phase1["source_inventory"],
            "strategy_map": phase1["strategy_map"],
            "section_map": phase1["section_map"],
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

        submitted_strategy_map = request.data.get("strategy_map")
        if isinstance(submitted_strategy_map, dict):
            phase1_results = dict(job.phase1_results or {})
            strategy_map = dict(submitted_strategy_map)
            strategy_map["status"] = "reviewed"
            phase1_results["strategy_map"] = strategy_map
            job.phase1_results = phase1_results

        def has_operator_section_review() -> bool:
            section_map = (job.phase1_results or {}).get("section_map") or {}
            for file_map in (section_map.get("files") or {}).values():
                for section in file_map.get("sections") or []:
                    if (
                        section.get("operator_label")
                        or section.get("operator_notes")
                        or section.get("operator_decision")
                        or section.get("operator_confidence")
                    ):
                        return True
            return False

        requested_mode = (request.data.get("analysis_mode") or "").strip().lower()
        if requested_mode in {"curated", "deep"}:
            analysis_mode = requested_mode
        else:
            analysis_mode = "curated" if has_operator_section_review() else "deep"

        phase2_results = dict(job.phase2_results or {})
        phase2_results.setdefault("files", {})
        phase2_results["analysis_mode"] = analysis_mode
        phase2_results["analysis_queue"] = {
            "status": "queued",
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "files": [],
        }

        job.status = CatalystParseJob.STATUS_ANALYZING
        job.phase2_results = phase2_results
        job.save(update_fields=["status", "client_context", "phase1_results", "phase2_results"])

        # Enqueue one task per file
        files_queued = 0
        strategy_files = (job.phase1_results.get("strategy_map") or {}).get("files", {})
        for file_entry in job.uploaded_files:
            filename = file_entry["filename"]
            strategy_row = strategy_files.get(filename, {})
            operator_decision = strategy_row.get("operator_decision")
            if operator_decision in {"skip", "hold", "misc"}:
                logger.info(
                    "[catalyst] Phase 2 skip — job=%s file=%s operator_decision=%s",
                    job.id,
                    filename,
                    operator_decision,
                )
                continue
            task_result = run_file_semantic_analysis.apply_async(
                args=[str(job.id), filename],
                queue="catalyst",
            )
            phase2_results["analysis_queue"]["files"].append({
                "filename": filename,
                "task_id": task_result.id,
                "status": "queued",
            })
            logger.info(
                "[catalyst] Phase 2 queued — job=%s file=%s task_id=%s queue=catalyst",
                job.id,
                filename,
                task_result.id,
            )
            files_queued += 1

        if files_queued == 0:
            job.status = CatalystParseJob.STATUS_COMPLETE
            job.phase2_results = {
                "files": {},
                "merged_registers": [],
                "summary": "No files queued; all sources were skipped or held in Strategy Review.",
            }
            job.save(update_fields=["status", "phase2_results"])
        else:
            job.phase2_results = phase2_results
            job.save(update_fields=["phase2_results"])

        logger.info(
            "[catalyst] Phase 2 started — job=%s files_queued=%d mode=%s",
            job.id,
            files_queued,
            analysis_mode,
        )

        return Response({
            "job_id": str(job.id),
            "status": job.status,
            "files_queued": files_queued,
            "analysis_mode": analysis_mode,
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
        queued_files = (job.phase2_results.get("analysis_queue") or {}).get("files") or []
        files_total = len(queued_files) or len(job.uploaded_files)

        resp: dict = {
            "job_id": str(job.id),
            "status": job.status,
            "files_done": files_done,
            "files_total": files_total,
        }
        if job.phase2_results.get("analysis_mode"):
            resp["analysis_mode"] = job.phase2_results.get("analysis_mode")
        if job.phase2_results.get("analysis_queue"):
            resp["analysis_queue"] = job.phase2_results.get("analysis_queue")
        if job.phase2_results.get("analysis_started"):
            resp["analysis_started"] = job.phase2_results.get("analysis_started")
        if job.phase1_results.get("source_inventory"):
            resp["source_inventory"] = job.phase1_results.get("source_inventory")
        if job.phase1_results.get("strategy_map"):
            resp["strategy_map"] = job.phase1_results.get("strategy_map")
        if job.phase1_results.get("section_map"):
            resp["section_map"] = job.phase1_results.get("section_map")

        if job.status == CatalystParseJob.STATUS_COMPLETE:
            resp["merged_registers"] = job.phase2_results.get("merged_registers", [])
            resp["completed_at"] = job.completed_at.isoformat() if job.completed_at else None

        return Response(resp, status=status.HTTP_200_OK)


class LatestParseJobReviewView(APIView):
    """
    GET /api/catalyst/groups/{slug}/parse-jobs/latest-review/

    Restores the latest saved Phase 1 inventory/strategy/section review for
    browser reloads or operator handoffs. This does not re-read source files.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, slug):
        group = get_object_or_404(Group, slug=slug, deleted_at__isnull=True)
        if not _is_group_admin(request.user, group):
            return Response({"detail": "Admin access required."}, status=status.HTTP_403_FORBIDDEN)

        from catalyst.models import CatalystParseJob

        job = None
        for candidate_status in (
            CatalystParseJob.STATUS_COMPLETE,
            CatalystParseJob.STATUS_ANALYZING,
            CatalystParseJob.STATUS_PHASE1_COMPLETE,
        ):
            for candidate in (
                CatalystParseJob.objects
                .filter(group=group, status=candidate_status)
                .order_by("-created_at")
            ):
                phase1 = candidate.phase1_results or {}
                if phase1.get("source_inventory") or phase1.get("strategy_map") or phase1.get("section_map"):
                    job = candidate
                    break
            if job:
                break

        if not job:
            return Response(
                {"detail": "No saved inventory review found for this group."},
                status=status.HTTP_404_NOT_FOUND,
            )

        phase1 = job.phase1_results or {}
        inventory = phase1.get("source_inventory") or {}
        inventory_files = inventory.get("files") or []
        skipped_duplicates = [
            item.get("filename")
            for item in inventory_files
            if item.get("filename") and (
                item.get("duplicate_of")
                or item.get("process_decision") in {"skipped_duplicate", "skipped_duplicate_text"}
            )
        ]
        files = []
        uploaded_by_name = {
            item.get("filename"): item
            for item in (job.uploaded_files or [])
            if item.get("filename")
        }
        for item in inventory_files:
            filename = item.get("filename")
            if not filename or item.get("duplicate_of"):
                continue
            uploaded = uploaded_by_name.get(filename, {})
            files.append({
                "filename": filename,
                "file_type": item.get("file_type") or uploaded.get("file_type") or "unknown",
                "registers": [],
                "skipped": [],
                "file_notes": "Recovered from saved inventory review.",
            })

        return Response({
            "job_id": str(job.id),
            "status": job.status,
            "phase1_results": phase1,
            "source_inventory": phase1.get("source_inventory"),
            "strategy_map": phase1.get("strategy_map"),
            "section_map": phase1.get("section_map"),
            "files": files,
            "skipped_duplicates": skipped_duplicates,
        }, status=status.HTTP_200_OK)


class ParseJobSectionMapView(APIView):
    """
    PATCH /api/catalyst/groups/{slug}/parse-jobs/{job_id}/section-map/

    Saves operator labels, decisions, and notes for one source section.
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request, slug, job_id):
        group = get_object_or_404(Group, slug=slug, deleted_at__isnull=True)
        if not _is_group_admin(request.user, group):
            return Response({"detail": "Admin access required."}, status=status.HTTP_403_FORBIDDEN)

        from catalyst.models import CatalystParseJob

        try:
            job = CatalystParseJob.objects.get(pk=job_id, group=group)
        except CatalystParseJob.DoesNotExist:
            return Response({"detail": "Job not found."}, status=status.HTTP_404_NOT_FOUND)

        filename = request.data.get("filename")
        section_id = request.data.get("section_id")
        if not filename or not section_id:
            return Response({"detail": "filename and section_id are required."}, status=status.HTTP_400_BAD_REQUEST)

        phase1_results = dict(job.phase1_results or {})
        section_map = dict(phase1_results.get("section_map") or {})
        files = dict(section_map.get("files") or {})
        file_map = dict(files.get(filename) or {})
        sections = list(file_map.get("sections") or [])
        updated = False

        combine_with_next = bool(request.data.get("combine_with_next"))
        allowed_keys = {"operator_label", "operator_decision", "operator_notes", "operator_confidence"}
        for idx, section in enumerate(sections):
            if section.get("section_id") != section_id:
                continue
            next_section = dict(section)
            for key in allowed_keys:
                if key in request.data:
                    next_section[key] = request.data.get(key) or ""
            if combine_with_next:
                if idx + 1 >= len(sections):
                    return Response({"detail": "No following section to combine."}, status=status.HTTP_400_BAD_REQUEST)
                merged_section = dict(sections[idx + 1])
                next_section["title"] = f"{next_section.get('title') or section_id} + {merged_section.get('title') or merged_section.get('section_id')}"
                next_section["content_markdown"] = "\n\n".join(
                    part for part in [
                        next_section.get("content_markdown") or "",
                        merged_section.get("content_markdown") or "",
                    ]
                    if part.strip()
                )
                next_section["content_chars"] = len(next_section["content_markdown"])
                next_section["end_char"] = merged_section.get("end_char", next_section.get("end_char"))
                next_section["merged_section_ids"] = [
                    *(next_section.get("merged_section_ids") or [section_id]),
                    *(merged_section.get("merged_section_ids") or [merged_section.get("section_id")]),
                ]
                next_section["merged_titles"] = [
                    *(next_section.get("merged_titles") or [section.get("title")]),
                    *(merged_section.get("merged_titles") or [merged_section.get("title")]),
                ]
            sections[idx] = next_section
            if combine_with_next:
                del sections[idx + 1]
            updated = True
            break

        if not updated:
            return Response({"detail": "Section not found."}, status=status.HTTP_404_NOT_FOUND)

        file_map["sections"] = sections
        file_map["status"] = "operator_review"
        files[filename] = file_map
        section_map["files"] = files
        section_map["status"] = "operator_review"
        phase1_results["section_map"] = section_map
        job.phase1_results = phase1_results
        job.save(update_fields=["phase1_results"])

        return Response({"section_map": section_map}, status=status.HTTP_200_OK)


class ParseJobTuningNotesView(APIView):
    """
    POST /api/catalyst/groups/{slug}/parse-jobs/{job_id}/tuning-notes/

    Stores operator-level batch guidance alongside the Phase 1 review.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, slug, job_id):
        group = get_object_or_404(Group, slug=slug, deleted_at__isnull=True)
        if not _is_group_admin(request.user, group):
            return Response({"detail": "Admin access required."}, status=status.HTTP_403_FORBIDDEN)

        from catalyst.models import CatalystParseJob

        try:
            job = CatalystParseJob.objects.get(pk=job_id, group=group)
        except CatalystParseJob.DoesNotExist:
            return Response({"detail": "Job not found."}, status=status.HTTP_404_NOT_FOUND)

        note_text = (request.data.get("note") or "").strip()
        shape = (request.data.get("shape") or "").strip()
        field = (request.data.get("field") or "").strip()
        value = (request.data.get("value") or "").strip()
        confidence = (request.data.get("confidence") or "").strip()
        if not note_text and not (shape and field and value):
            return Response(
                {"detail": "A note or structured tuning field is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        phase1_results = dict(job.phase1_results or {})
        tuning_notes = list(phase1_results.get("tuning_notes") or [])
        tuning_note = {
            "id": str(uuid.uuid4()),
            "created_at": NOW_ISO(),
            "created_by": request.user.username,
            "scope": request.data.get("scope") or "phase1_review",
            "shape": shape,
            "field": field,
            "value": value,
            "confidence": confidence,
            "note": note_text,
        }
        tuning_notes.append(tuning_note)
        phase1_results["tuning_notes"] = tuning_notes
        job.phase1_results = phase1_results
        job.save(update_fields=["phase1_results"])

        return Response(
            {
                "tuning_note": tuning_note,
                "tuning_notes": tuning_notes,
                "phase1_results": phase1_results,
            },
            status=status.HTTP_201_CREATED,
        )


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
            # Fall back: prefer the newest completed reviewed job. Phase-one
            # jobs are usable, but should not outrank a completed curated pass.
            job = None
            for candidate_status in (
                CatalystParseJob.STATUS_COMPLETE,
                CatalystParseJob.STATUS_PHASE1_COMPLETE,
            ):
                for candidate in (
                    CatalystParseJob.objects
                    .filter(group=group, status=candidate_status)
                    .order_by("-created_at")
                ):
                    phase1 = candidate.phase1_results or {}
                    if phase1.get("source_inventory") or phase1.get("strategy_map") or phase1.get("section_map"):
                        job = candidate
                        break
                if job:
                    break
            if not job:
                return Response(
                    {"detail": "No usable parse job found for this group. Run Phase 1 first."},
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

        task = materialize_register_entities.apply_async(
            args=[slug, register_slug, str(job_id)],
            queue="catalyst",
        )
        logger.info(
            "[catalyst] materialize queued: group=%s register=%s job=%s task=%s by %s",
            slug, register_slug, job_id, task.id, request.user.username,
        )
        return Response({
            "status": "queued",
            "register": register_slug,
            "job_id": str(job_id),
            "task_id": task.id,
        })


class RegisterEntryListView(APIView):
    """
    GET /api/catalyst/groups/{slug}/registers/{register_slug}/entries/

    Returns all materialized entry files for a register as a list of
    {slug, title, status} objects. Entry files are any .md files in the
    register directory that are NOT _index.md.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, slug, register_slug):
        group = get_object_or_404(Group, slug=slug, deleted_at__isnull=True)
        if not _is_group_admin(request.user, group):
            return Response({"detail": "Admin access required."}, status=status.HTTP_403_FORBIDDEN)

        reg_dir = _codex_root(slug) / "CONTENT" / "registers" / register_slug
        if not reg_dir.exists():
            return Response({"entries": []})

        entries = []
        for md_file in sorted(reg_dir.glob("*.md")):
            if md_file.name == "_index.md":
                continue
            entry_slug = md_file.stem
            fm, _ = _parse_index(md_file)
            entries.append({
                "slug": entry_slug,
                "title": fm.get("title") or entry_slug.replace("-", " ").title(),
                "status": fm.get("status", "draft"),
            })

        return Response({"register": register_slug, "entries": entries})


class RegisterMaterializeProgressView(APIView):
    """
    GET /api/catalyst/groups/{slug}/registers/{register_slug}/materialize/progress/

    Returns the current materialization progress sidecar for a register.
    This is intentionally file-backed because materialization writes Codex
    artifacts incrementally and should be inspectable without task result state.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, slug, register_slug):
        group = get_object_or_404(Group, slug=slug, deleted_at__isnull=True)
        if not _is_group_admin(request.user, group):
            return Response({"detail": "Admin access required."}, status=status.HTTP_403_FORBIDDEN)

        progress_path = (
            _codex_root(slug)
            / "CONTENT"
            / "registers"
            / register_slug
            / "_materialization_progress.json"
        )
        if not progress_path.exists():
            return Response({
                "register": register_slug,
                "status": "not_started",
                "entry_count": 0,
                "source_files": [],
                "completed_files": [],
                "file_results": {},
            })
        try:
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return Response(
                {"detail": "Materialization progress file is not valid JSON."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        if not isinstance(progress, dict):
            progress = {}
        progress.setdefault("register", register_slug)
        progress.setdefault("status", "unknown")
        progress.setdefault("entry_count", 0)
        progress.setdefault("source_files", [])
        progress.setdefault("completed_files", [])
        progress.setdefault("file_results", {})
        return Response(progress)


class RegisterEntryDetailView(APIView):
    """
    GET  /api/catalyst/groups/{slug}/registers/{register_slug}/entries/{entry_slug}/
    PATCH /api/catalyst/groups/{slug}/registers/{register_slug}/entries/{entry_slug}/

    GET returns frontmatter + body_markdown for a single entry file.
    PATCH accepts body_markdown and/or status.
    """

    permission_classes = [IsAuthenticated]

    def _entry_path(self, slug, register_slug, entry_slug):
        return _codex_root(slug) / "CONTENT" / "registers" / register_slug / f"{entry_slug}.md"

    def get(self, request, slug, register_slug, entry_slug):
        group = get_object_or_404(Group, slug=slug, deleted_at__isnull=True)
        if not _is_group_admin(request.user, group):
            return Response({"detail": "Admin access required."}, status=status.HTTP_403_FORBIDDEN)

        path = self._entry_path(slug, register_slug, entry_slug)
        if not path.exists():
            return Response({"detail": "Entry not found."}, status=status.HTTP_404_NOT_FOUND)

        fm, body = _parse_index(path)
        return Response({
            "slug": entry_slug,
            "title": fm.get("title") or entry_slug.replace("-", " ").title(),
            "status": fm.get("status", "draft"),
            "frontmatter": fm,
            "body_markdown": body,
        })

    def patch(self, request, slug, register_slug, entry_slug):
        group = get_object_or_404(Group, slug=slug, deleted_at__isnull=True)
        if not _is_group_admin(request.user, group):
            return Response({"detail": "Admin access required."}, status=status.HTTP_403_FORBIDDEN)

        path = self._entry_path(slug, register_slug, entry_slug)
        if not path.exists():
            return Response({"detail": "Entry not found."}, status=status.HTTP_404_NOT_FOUND)

        fm, body = _parse_index(path)
        new_body = request.data.get("body_markdown", body)
        new_status = request.data.get("status")
        if new_status in ("draft", "canon", "pre-canon"):
            fm["status"] = new_status

        codex_root = _codex_root(slug)
        _write_index(path, fm, new_body)

        try:
            rel = str(path.relative_to(codex_root))
            _git(codex_root, "add", rel)
            _git(codex_root, "commit", "-m",
                 f"edit: {register_slug}/{entry_slug} — by {request.user.username} at {NOW_ISO()}")
        except Exception as exc:
            return Response({"detail": f"Saved but git commit failed: {exc}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"slug": entry_slug, "status": fm.get("status", "draft")})
