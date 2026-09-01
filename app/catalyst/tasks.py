# catalyst/tasks.py
"""
Celery tasks for the catalyst app.
Route: push queue (Celery-only; must not be consumed by Uvicorn).
"""

import json
import logging
import re
import subprocess
import urllib.parse
import uuid
import yaml
from datetime import datetime, timezone
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)


def _get_or_create_activation_invite(group):
    """
    For a newly activated Catalyst group with a ghost owner (is_active=False):
    create a GroupInvitation + InviteLink and return the activation URL.

    Returns None when the owner is already active (existing-group path) —
    callers should send workspace_url only in that case.
    """
    from django.contrib.auth import get_user_model
    from django.contrib.auth.tokens import default_token_generator
    from django.contrib.contenttypes.models import ContentType

    from groups.models import GroupMembership
    from groups.models.group import GroupInvitation, InvitationKind, InvitationStatus, InviteLink
    from utils.email.shortcode import generate_shortcode

    User = get_user_model()
    user_ct = ContentType.objects.get_for_model(User)

    # Find ghost owner — newly created Catalyst users are inactive until they set a password
    ghost_owner = User.objects.filter(
        id__in=GroupMembership.objects.filter(
            group=group,
            member_content_type=user_ct,
            roles__contains=["owner"],
            is_active=True,
        ).values_list("member_object_id", flat=True),
        is_active=False,
    ).first()

    if not ghost_owner:
        return None  # existing-group path — all owners already active

    # Use Client.created_by (the admin who ran the activation action) as invited_by
    invited_by = None
    try:
        if hasattr(group, "client") and group.client.created_by_id:
            invited_by = group.client.created_by
    except Exception:
        pass
    if not invited_by:
        invited_by = User.objects.filter(is_superuser=True).first()
    if not invited_by:
        logger.warning("[catalyst-invite] No admin user for invited_by on group %s", group.slug)
        return None

    # Ensure a pending GroupInvitation exists — accept_invite_by_shortcode requires one
    GroupInvitation.objects.get_or_create(
        invited_user=ghost_owner,
        group=group,
        invitation_status=InvitationStatus.PENDING,
        defaults={
            "invited_by": invited_by,
            "invitation_kind": InvitationKind.INVITE,
            "intended_roles": ["owner"],
            "email_status": "sent",
        },
    )

    # Get or create an InviteLink for the ghost user
    invite_link = InviteLink.objects.filter(user=ghost_owner, group=group, is_used=False).first()
    if not invite_link:
        invite_link = InviteLink.objects.create(
            user=ghost_owner,
            group=group,
            shortcode=generate_shortcode(),
            token=default_token_generator.make_token(ghost_owner),
            invited_by=invited_by,
        )

    frontend_url = getattr(settings, "FRONTEND_URL", "https://app.crossroads.place")
    url_template = getattr(settings, "CATALYST_TENANT_URL_TEMPLATE", "https://{slug}.apps.crossroads.place/app/groups/{slug}/catalyst")
    workspace_url = url_template.format(slug=group.slug)
    next_param = urllib.parse.quote(workspace_url, safe="")
    return f"{frontend_url}/app/invitations/accept/{invite_link.shortcode}/new?next={next_param}"


@shared_task(
    name="catalyst.tasks.provision_catalyst_for_group",
    bind=True,
    max_retries=1,
    default_retry_delay=30,
)
def provision_catalyst_for_group(self, group_id: int) -> None:
    """
    Self-serve Catalyst provisioning for an existing group whose owner already
    has an active Crossroads account (Path B).  Runs Codex steps 2–7 against
    a GroupAdapter shim — no BusinessProspect, no activation email.
    Sets catalyst_status='ready' and catalyst_enabled=True on success,
    or catalyst_status='failed' on error.
    """
    from groups.models.group import Group
    from catalyst.services.activation import CatalystActivationService, CatalystActivationError

    try:
        group = Group.objects.get(pk=group_id)
    except Group.DoesNotExist:
        logger.error("[catalyst-provision] Group %s not found", group_id)
        return

    class _GroupAdapter:
        """Minimal shim so CatalystActivationService can work without a BusinessProspect."""
        def __init__(self, g):
            self.slug = g.slug
            self.name = g.title or g.slug
            self.converted_to_group = g
            self.org_description = g.summary or ""
            self.knowledge_goal = ""
            self.primary_contact_email = None

    service = CatalystActivationService(_GroupAdapter(group))

    try:
        service.init_codex()
        service.copy_seed_files()
        service.stamp_manifest_hashes()
        service.stamp_fixture_provenance()
        service.seed_ir()
        service.generate_docent()
    except CatalystActivationError as exc:
        logger.error("[catalyst-provision] Failed for group %s: %s", group.slug, exc)
        Group.objects.filter(pk=group_id).update(catalyst_status="failed")
        return

    Group.objects.filter(pk=group_id).update(
        catalyst_status="ready",
        catalyst_enabled=True,
    )
    logger.info("[catalyst-provision] Provisioning complete for group %s", group.slug)


@shared_task(
    name="catalyst.tasks.send_catalyst_activation_email",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def send_catalyst_activation_email(self, prospect_id: int) -> None:
    """
    Send the Catalyst activation email to the primary contact for a prospect.
    Expects prospect.converted_to_group to be set before queuing.
    """
    from django.conf import settings
    from django.template.loader import render_to_string

    from prospects.models import BusinessProspect
    from utils.email.mailjet_client import MailjetSendError, send_via_mailjet

    try:
        prospect = BusinessProspect.objects.select_related("converted_to_group").get(pk=prospect_id)
    except BusinessProspect.DoesNotExist:
        logger.error("[catalyst-email] Prospect %s not found — aborting", prospect_id)
        return

    to_email = prospect.primary_contact_email
    if not to_email:
        logger.warning(
            "[catalyst-email] Prospect %s has no primary_contact_email — skipping", prospect_id
        )
        return

    group = prospect.converted_to_group
    if not group:
        logger.error("[catalyst-email] Prospect %s has no converted_to_group — aborting", prospect_id)
        return

    url_template = getattr(settings, "CATALYST_TENANT_URL_TEMPLATE", "https://{slug}.apps.crossroads.place/app/groups/{slug}/catalyst")
    workspace_url = url_template.format(slug=group.slug)
    contact_name = prospect.primary_contact_name or prospect.name

    # Ghost owner → include account activation link; existing users → workspace only
    activation_url = _get_or_create_activation_invite(group)
    if activation_url:
        logger.info("[catalyst-email] Ghost owner detected on group %s — activation invite created", group.slug)
    else:
        logger.info("[catalyst-email] Existing-user path for group %s — no activation invite needed", group.slug)

    context = {
        "contact_name": contact_name,
        "org_name": prospect.name,
        "group_slug": group.slug,
        "workspace_url": workspace_url,
        "activation_url": activation_url,
    }

    try:
        text_body = render_to_string("email/catalyst_activation.txt", context)
        html_body = render_to_string("email/catalyst_activation.html", context)
    except Exception as exc:
        logger.exception("[catalyst-email] Template render failed for prospect %s", prospect_id)
        raise self.retry(exc=exc)

    try:
        message_id = send_via_mailjet(
            to_email=to_email,
            to_name=contact_name,
            subject=f"Your Catalyst workspace is ready — {prospect.name}",
            text_body=text_body,
            html_body=html_body,
            custom_id=f"catalyst-activation-{prospect_id}",
        )
        logger.info(
            "[catalyst-email] SENT prospect=%s email=%s message_id=%s",
            prospect_id, to_email, message_id,
        )
    except MailjetSendError as exc:
        logger.exception("[catalyst-email] Mailjet failed for prospect %s", prospect_id)
        raise self.retry(exc=exc)


# ── Tenant runtime pre-flight ─────────────────────────────────────────────────

def _runtime_preflight(group, codex_cwd: str) -> tuple[str | None, str | None]:
    """
    Verify the tenant's Claude runtime is ready before any extraction job.

    Returns (linux_user, None) on success, (None, error_msg) when the runtime is
    absent, not ready, or fails pre-flight — in which case the caller must not
    write Codex files and should record the error against the job.

    Side effect: if pre-flight detects auth_failure, transitions the runtime to
    login_required so the admin knows they need to re-authenticate.
    """
    from django.contrib.contenttypes.models import ContentType
    from claude.service import run_blocking
    from tenant_runtime.models import TenantClaudeRuntime

    ct = ContentType.objects.get_for_model(group)
    runtime = TenantClaudeRuntime.objects.filter(
        tenant_content_type=ct,
        tenant_object_id=group.id,
    ).first()

    if not runtime:
        # No runtime configured — run under the server process (legacy/dev path)
        return None, None

    if runtime.status != TenantClaudeRuntime.STATUS_READY:
        return None, f"auth_failure: runtime status={runtime.status} for group={group.slug}"

    result = run_blocking("say ok", cwd=codex_cwd, run_as_user=runtime.linux_user, timeout=30)
    if result.failure == "auth_failure":
        runtime.status = TenantClaudeRuntime.STATUS_LOGIN_REQUIRED
        runtime.last_verification_error = "Pre-flight failed before extraction job."
        runtime.save(update_fields=["status", "last_verification_error", "updated_at"])
        return None, f"auth_failure: pre-flight verification failed for group={group.slug}"

    if result.failure:
        return None, f"preflight_error: {result.failure} for group={group.slug}"

    return runtime.linux_user, None


def _operator_section_brief(job, filename: str, max_chars: int = 12_000) -> str:
    """
    Compact saved Phase 1 section review into prompt context.

    The full section map can be large; Phase 2 only needs the operator's labels,
    decisions, confidence, and short notes so the semantic pass counts the right
    entities instead of re-guessing from raw document structure.
    """
    phase1 = job.phase1_results or {}
    files = (phase1.get("section_map") or {}).get("files") or {}
    file_map = files.get(filename) or {}
    sections = file_map.get("sections") or []
    if not sections:
        return ""

    lines: list[str] = [f"File: {filename}"]
    for section in sections:
        decision = section.get("operator_decision") or "review"
        label = section.get("operator_label") or section.get("proposed_label") or ""
        confidence = section.get("operator_confidence") or ""
        notes = (section.get("operator_notes") or "").strip()
        if decision == "review" and not notes and not section.get("operator_label") and not confidence:
            continue

        title = section.get("title") or section.get("section_id") or "Untitled section"
        prefix = f"- {section.get('section_id')}: {title}"
        details = [f"decision={decision}"]
        if label:
            details.append(f"label={label}")
        if confidence:
            details.append(f"confidence={confidence}")
        lines.append(f"{prefix} ({', '.join(details)})")
        if notes:
            compact_notes = " ".join(notes.split())
            lines.append(f"  notes: {compact_notes[:600]}")

    brief = "\n".join(lines)
    return brief[:max_chars]


def _has_operator_section_review(job, filename: str) -> bool:
    phase1 = job.phase1_results or {}
    files = (phase1.get("section_map") or {}).get("files") or {}
    file_map = files.get(filename) or {}
    for section in file_map.get("sections") or []:
        if (
            section.get("operator_label")
            or section.get("operator_notes")
            or section.get("operator_decision")
            or section.get("operator_confidence")
        ):
            return True
    return False


def _operator_registers_from_section_map(job, filename: str) -> list[dict]:
    """Infer register candidates directly from saved operator section review."""
    from catalyst.services.parse_service import register_slug_for_entity

    phase1 = job.phase1_results or {}
    files = (phase1.get("section_map") or {}).get("files") or {}
    file_map = files.get(filename) or {}
    sections = file_map.get("sections") or []
    counters = {
        "meals": set(),
        "recipes": set(),
        "ingredients": set(),
        "suppliers": set(),
        "supplies": set(),
        "orders": set(),
        "dietary-restrictions": set(),
        "prep-tasks": set(),
    }
    examples: dict[str, list[str]] = {key: [] for key in counters}

    def add(slug: str, name: str) -> None:
        name = " ".join(str(name or "").split()).strip(" :-")
        if not name:
            return
        key = name.lower()
        if key in counters[slug]:
            return
        counters[slug].add(key)
        if len(examples[slug]) < 5:
            examples[slug].append(name)

    def split_names(value: str) -> list[str]:
        value = re.sub(r"^\s*[-*]\s*", "", value.strip())
        value = re.sub(r"^(recipe|recipes|ingredient|ingredients|supplier|suppliers|supply|supplies|order|orders)\s*[:=]\s*", "", value, flags=re.I)
        parts = re.split(r"\s*,\s*|\s+ and \s+|\s*/\s*", value)
        return [part.strip(" .;:-") for part in parts if part.strip(" .;:-")]

    for section in sections:
        decision = section.get("operator_decision") or "review"
        if decision in {"skip", "hold", "misc"}:
            continue
        title = section.get("title") or ""
        label_text = str(section.get("operator_label") or "").lower()
        notes = section.get("operator_notes") or ""
        text = f"{label_text}\n{notes}".lower()

        if "recipe" in label_text:
            add("recipes", title)
        if "meal" in label_text:
            add("meals", title)
        if "order" in label_text:
            add("orders", title)
        if "supply" in label_text:
            add("supplies", title)
        if "supplier" in label_text or "purveyor" in label_text:
            add("suppliers", title)

        if re.search(r"\bmeal\b|meal\.", text):
            add("meals", title)
        if re.search(r"\border\b|order\.", text):
            add("orders", title)
        if re.search(r"\bsupplies\b|\bsupply\b", text):
            add("supplies", title)
        if re.search(r"\bsupplier\b|\bsuppliers\b|\bpurveyor\b", text):
            add("suppliers", title)
        if re.search(r"dietary|vegan|vegetarian|gluten|dairy|halal|kosher", text):
            add("dietary-restrictions", title)
        if re.search(r"\bprep\b|prep_task|prep task", text):
            add("prep-tasks", title)

        for raw_line in notes.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lower = line.lower()
            if re.match(r"^recipes?\s*(?:\([^)]+\))?\s*[:=]", lower):
                for name in split_names(line):
                    add("recipes", name)
            elif re.match(r"^ingredients?\s*[:=]", lower):
                for name in split_names(line):
                    add("ingredients", name)
            elif re.match(r"^(suppliers?|purveyor)\s*[:=]", lower) or re.match(r"^order\.supplier\s*[:=]", lower):
                for name in split_names(line):
                    add("suppliers", name)
            elif re.match(r"^supplies?\s*[:=]", lower):
                for name in split_names(line):
                    add("supplies", name)

    labels = {
        "meals": "Meals",
        "recipes": "Recipes",
        "ingredients": "Ingredients",
        "suppliers": "Suppliers",
        "supplies": "Supplies",
        "orders": "Orders",
        "dietary-restrictions": "Dietary Restrictions",
        "prep-tasks": "Prep Tasks",
    }
    registers = []
    for slug, names in counters.items():
        if not names:
            continue
        entity_plural = labels[slug].lower()
        registers.append({
            "slug": register_slug_for_entity(slug, entity_plural),
            "display_name": labels[slug],
            "entry_count": len(names),
            "source_file": filename,
            "canon_synonym": "Canon",
            "notes": "Operator-reviewed section annotations. e.g. " + ", ".join(examples[slug]),
            "confidence": "medium",
            "columns": [],
        })
    return registers


def _mark_phase2_file_state(job_id: str, filename: str, state: str, task_id: str | None = None) -> None:
    from catalyst.models import CatalystParseJob

    with transaction.atomic():
        job = CatalystParseJob.objects.select_for_update().get(pk=job_id)
        p2 = job.phase2_results or {}
        p2.setdefault("files", {})
        started = p2.setdefault("analysis_started", {})
        started[filename] = {
            "state": state,
            "task_id": task_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        queue = p2.get("analysis_queue") or {}
        for row in queue.get("files") or []:
            if row.get("filename") == filename:
                row["status"] = state
                row["updated_at"] = started[filename]["updated_at"]
                if task_id:
                    row["task_id"] = task_id
        p2["analysis_queue"] = queue
        job.phase2_results = p2
        job.save(update_fields=["phase2_results"])


# ── Phase 2 — per-file semantic analysis ──────────────────────────────────────

@shared_task(
    name="catalyst.tasks.run_file_semantic_analysis",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    soft_time_limit=240,
    time_limit=300,
)
def run_file_semantic_analysis(self, job_id: str, filename: str) -> None:
    """
    Run semantic_analyze() on one uploaded file for a CatalystParseJob.
    Writes the AI result to phase2_results.files[filename].
    After each file completes, checks whether all files are done and
    triggers finalize_parse_job if so.
    """
    from catalyst.models import CatalystParseJob
    from catalyst.services.parse_service import semantic_analyze

    task_id = getattr(self.request, "id", None)
    logger.info(
        "[catalyst-parse] Phase 2 task entered — job=%s file=%s task_id=%s",
        job_id,
        filename,
        task_id,
    )

    try:
        job = CatalystParseJob.objects.get(pk=job_id)
    except CatalystParseJob.DoesNotExist:
        logger.error("[catalyst-parse] Job %s not found — aborting task for %s", job_id, filename)
        return

    try:
        _mark_phase2_file_state(job_id, filename, "started", task_id)
    except Exception:
        logger.exception("[catalyst-parse] Failed to mark task started — job=%s file=%s", job_id, filename)

    phase2_mode = (job.phase2_results or {}).get("analysis_mode")
    if phase2_mode not in {"curated", "deep"}:
        phase2_mode = "curated" if _has_operator_section_review(job, filename) else "deep"
    operator_registers = _operator_registers_from_section_map(job, filename)
    if phase2_mode == "curated":
        logger.info(
            "[catalyst-parse] Curated Phase 2 from operator review — job=%s file=%s registers=%d",
            job_id,
            filename,
            len(operator_registers),
        )
        ai_result: dict = {
            "count": sum(int(reg.get("entry_count") or 0) for reg in operator_registers),
            "entity_type": "operator reviewed register",
            "entity_plural": "operator reviewed registers",
            "confidence": "medium",
            "notes": "Derived from saved human section review; deep semantic analysis skipped.",
            "registers": operator_registers,
            "analysis_mode": "curated",
        }
    elif not (job.job_dir() / filename).exists():
        logger.error("[catalyst-parse] File %s not found on disk for job %s", filename, job_id)
        ai_result = {"error": "file not found on disk", "count": 0}
    else:
        codex_cwd = str(Path(settings.CATALYST_CODEX_ROOT) / job.group.slug)
        run_as_user, preflight_error = _runtime_preflight(job.group, codex_cwd)
        if preflight_error:
            logger.warning("[catalyst-parse] Pre-flight failed for job=%s file=%s: %s", job_id, filename, preflight_error)
            ai_result = {"error": preflight_error, "count": 0}
        else:
            ai_result = {}
        data = (job.job_dir() / filename).read_bytes()
        if not ai_result:
            logger.info("[catalyst-parse] Deep semantic analysis started — file=%s job=%s", filename, job_id)
            try:
                ai = semantic_analyze(
                    filename,
                    data,
                    codex_cwd=codex_cwd,
                    client_context=job.client_context or None,
                    operator_context=_operator_section_brief(job, filename),
                    timeout=210,
                    run_as_user=run_as_user,
                )
                ai_result = ai if ai is not None else {"count": 0, "notes": "timed out or skipped"}
                if operator_registers:
                    ai_result["registers"] = operator_registers
            except Exception as exc:
                logger.exception("[catalyst-parse] semantic_analyze failed for %s", filename)
                ai_result = {"error": str(exc), "count": 0}
                if operator_registers:
                    ai_result["registers"] = operator_registers

    # Atomically update phase2_results
    with transaction.atomic():
        job_fresh = CatalystParseJob.objects.select_for_update().get(pk=job_id)
        p2 = job_fresh.phase2_results or {}
        files_dict: dict = p2.get("files", {})
        files_dict[filename] = ai_result
        p2["files"] = files_dict
        completed_at = datetime.now(timezone.utc).isoformat()
        started = p2.setdefault("analysis_started", {})
        started[filename] = {
            "state": "complete",
            "task_id": task_id,
            "updated_at": completed_at,
        }
        queue = p2.get("analysis_queue") or {}
        for row in queue.get("files") or []:
            if row.get("filename") == filename:
                row["status"] = "complete"
                row["updated_at"] = completed_at
                if task_id:
                    row["task_id"] = task_id
        p2["analysis_queue"] = queue
        job_fresh.phase2_results = p2
        job_fresh.save(update_fields=["phase2_results"])
        files_done = len(files_dict)
        queued_files = (p2.get("analysis_queue") or {}).get("files") or []
        files_total = len(queued_files) or len(job_fresh.uploaded_files)

    logger.info(
        "[catalyst-parse] %s done (job=%s) — %d/%d files complete",
        filename, job_id, files_done, files_total,
    )

    if files_done >= files_total:
        finalize_parse_job.apply_async(args=[job_id], queue="catalyst")


@shared_task(
    name="catalyst.tasks.finalize_parse_job",
    bind=True,
    max_retries=1,
    default_retry_delay=15,
)
def finalize_parse_job(self, job_id: str) -> None:
    """
    Called once all file tasks are complete.
    Builds merged_registers from AI results, sets status=complete,
    sends email notification to the job creator.
    """
    from catalyst.models import CatalystParseJob
    from catalyst.services.parse_service import register_slug_for_entity, slugify

    try:
        with transaction.atomic():
            job = CatalystParseJob.objects.select_for_update().get(pk=job_id)

            if job.status == CatalystParseJob.STATUS_COMPLETE:
                logger.info("[catalyst-finalize] Job %s already complete — skipping", job_id)
                return

            # Build merged_registers from AI results
            files_results: dict = job.phase2_results.get("files", {})
            merged: dict[str, dict] = {}

            for filename, ai in files_results.items():
                if not ai:
                    continue
                register_candidates = ai.get("registers") if isinstance(ai.get("registers"), list) else []
                if not register_candidates and ai.get("count", 0) > 0:
                    ai_slug = register_slug_for_entity(ai.get("entity_type"), ai.get("entity_plural"))
                    register_candidates = [{
                        "slug": ai_slug,
                        "display_name": ai.get("entity_plural", ai.get("entity_type", "records")).title(),
                        "entry_count": ai["count"],
                        "source_file": filename,
                        "canon_synonym": "Canon",
                        "notes": f"e.g. {', '.join(ai['examples'][:3])}" if ai.get("examples") else "",
                        "confidence": ai.get("confidence", "medium"),
                        "columns": [],
                    }]
                for reg in register_candidates:
                    ai_slug = register_slug_for_entity(reg.get("slug"), reg.get("display_name"))
                    entry_count = int(reg.get("entry_count") or reg.get("count") or 0)
                    if entry_count <= 0:
                        continue
                    ai_notes = reg.get("notes") or ""
                    if ai_slug in merged:
                        merged[ai_slug]["entry_count"] += entry_count
                        if filename not in merged[ai_slug]["source_file"]:
                            merged[ai_slug]["source_file"] += f", {filename}"
                        if ai_notes:
                            merged[ai_slug]["notes"] += f"; {ai_notes}"
                    else:
                        merged[ai_slug] = {
                            "slug": ai_slug,
                            "display_name": reg.get("display_name") or ai_slug.replace("-", " ").title(),
                            "entry_count": entry_count,
                            "source_file": reg.get("source_file") or filename,
                            "canon_synonym": reg.get("canon_synonym") or "Canon",
                            "notes": ai_notes,
                            "confidence": reg.get("confidence") or ai.get("confidence", "medium"),
                            "columns": reg.get("columns") or [],
                        }

            p2 = job.phase2_results
            p2["merged_registers"] = list(merged.values())
            job.phase2_results = p2
            job.status = CatalystParseJob.STATUS_COMPLETE
            job.completed_at = datetime.now(timezone.utc)
            job.save(update_fields=["phase2_results", "status", "completed_at"])

    except CatalystParseJob.DoesNotExist:
        logger.error("[catalyst-finalize] Job %s not found", job_id)
        return

    logger.info(
        "[catalyst-finalize] Job %s complete — %d registers merged",
        job_id, len(merged),
    )

    # Send email notification (outside transaction — network call)
    _send_parse_complete_email(job)


def _send_parse_complete_email(job) -> None:
    """Send a plain-text notification that Phase 2 analysis is ready to review."""
    from utils.email.mailjet_client import MailjetSendError, send_via_mailjet

    user = job.created_by
    if not user or not user.email:
        logger.warning("[catalyst-email] No email for job %s creator — skipping notification", job.id)
        return

    group_slug = job.group.slug
    group_name = job.group.title or group_slug
    frontend_url = getattr(settings, "FRONTEND_URL", "https://app.crossroads.place")
    review_url = f"{frontend_url}/app/groups/{group_slug}/catalyst"

    merged = job.phase2_results.get("merged_registers", [])
    summary_lines = [
        f"  • {r['entry_count']} {r['display_name'].lower()}"
        for r in merged if r.get("entry_count", 0) > 0
    ]
    summary = "\n".join(summary_lines) if summary_lines else "  (no entities extracted)"

    text_body = (
        f"Hi {user.first_name or user.username},\n\n"
        f"Your Catalyst analysis for {group_name} is ready to review.\n\n"
        f"We found:\n{summary}\n\n"
        f"Review and accept into your Codex:\n{review_url}\n\n"
        "— Crossroads Catalyst\n"
    )

    try:
        send_via_mailjet(
            to_email=user.email,
            to_name=user.get_full_name() or user.username,
            subject=f"Your Catalyst analysis is ready — {group_name}",
            text_body=text_body,
            html_body=text_body.replace("\n", "<br>"),
            custom_id=f"catalyst-parse-complete-{job.id}",
        )
        job.notified = True
        job.save(update_fields=["notified"])
        logger.info("[catalyst-email] Sent parse-complete email for job %s to %s", job.id, user.email)
    except MailjetSendError as exc:
        logger.exception("[catalyst-email] Mailjet failed for job %s: %s", job.id, exc)


# ── Phase 3 — Entity materialization ──────────────────────────────────────────

def _git_codex(codex_root: Path, *args) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=codex_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(str(a) for a in args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _rewrite_register_body(index_path: Path, new_body: str) -> None:
    """Replace the body section of a register _index.md without touching frontmatter."""
    raw = index_path.read_text(encoding="utf-8")
    parts = raw.split("---", 2)
    if len(parts) >= 3:
        fm_str = parts[1]
        index_path.write_text(f"---{fm_str}---\n\n{new_body}\n", encoding="utf-8")
    else:
        index_path.write_text(raw + f"\n\n{new_body}\n", encoding="utf-8")


def _fm_from_index(index_path: Path) -> dict:
    raw = index_path.read_text(encoding="utf-8")
    parts = raw.split("---", 2)
    if len(parts) >= 3:
        try:
            return yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            return {}
    return {}


def _materialization_source_files(job, source_file_str: str, register_slug: str) -> list[str]:
    """
    Pick source files for Phase 3 materialization.

    Prefer register/source metadata from confirmed registers, Phase 2 merged
    results, and Phase 1 structural results. Fall back to every uploaded file
    only when no known source mapping exists.
    """
    uploaded_filenames = [
        str(f.get("filename") or "")
        for f in (job.uploaded_files or [])
        if f.get("filename")
    ]
    uploaded_by_stripped = {
        filename.strip(): filename
        for filename in uploaded_filenames
    }
    selected: list[str] = []

    def add_candidate(source: str) -> None:
        if not source:
            return
        exact = source if source in uploaded_filenames else uploaded_by_stripped.get(source.strip(), source)
        if exact:
            selected.append(exact)

    for filename in uploaded_filenames:
        if source_file_str == filename or filename in source_file_str:
            add_candidate(filename)

    def add_source(value) -> None:
        if not value:
            return
        value_str = str(value)
        for filename in uploaded_filenames:
            if value_str == filename or filename in value_str:
                add_candidate(filename)
                return
        for source in str(value).split(","):
            add_candidate(source)

    for reg in job.phase2_results.get("merged_registers", []) if isinstance(job.phase2_results, dict) else []:
        if reg.get("slug") == register_slug:
            add_source(reg.get("source_file") or reg.get("sourceFile"))

    if not selected:
        phase1 = job.phase1_results or {}
        for bucket in ("aligned", "unexpected"):
            for reg in phase1.get(bucket, []) or []:
                if reg.get("slug") == register_slug:
                    add_source(reg.get("source_file") or reg.get("sourceFile"))

    if not selected:
        selected = [str(f.get("filename") or "") for f in (job.uploaded_files or [])]

    deduped: list[str] = []
    seen: set[str] = set()
    for filename in selected:
        if filename and filename not in seen:
            seen.add(filename)
            deduped.append(filename)
    return deduped


def _section_mentions_register(section: dict, register_slug: str) -> bool:
    decision = (section.get("operator_decision") or "review").strip().lower()
    if decision in {"ignore", "skip", "hold", "misc"}:
        return False

    label = str(section.get("operator_label") or section.get("proposed_label") or "").lower()
    notes = str(section.get("operator_notes") or "").lower()
    title = str(section.get("title") or "").lower()
    haystack = f"{label}\n{notes}\n{title}"

    if register_slug == "recipes":
        return any(
            term in haystack
            for term in (
                "recipe",
                "recipes",
                "recipe.",
                "ingredients",
                "instructions",
                "sauce",
                "dressing",
                "aioli",
                "meal",
            )
        )
    if register_slug == "meals":
        return any(term in haystack for term in ("meal", "breakfast", "lunch", "dinner"))
    if register_slug == "ingredients":
        return any(term in haystack for term in ("ingredient", "ingredients", "recipe.ingredients"))
    return register_slug.replace("-", " ") in haystack or register_slug.rstrip("s") in haystack


def _reviewed_sections_for_materialization(job, filename: str, register_slug: str) -> list[dict]:
    phase1 = job.phase1_results or {}
    file_map = ((phase1.get("section_map") or {}).get("files") or {}).get(filename) or {}
    sections = file_map.get("sections") or []
    return [
        section
        for section in sections
        if str(section.get("content_markdown") or "").strip()
        and _section_mentions_register(section, register_slug)
    ]


def _has_operator_reviewed_sections(job, filename: str) -> bool:
    phase1 = job.phase1_results or {}
    file_map = ((phase1.get("section_map") or {}).get("files") or {}).get(filename) or {}
    for section in file_map.get("sections") or []:
        if (
            section.get("operator_label")
            or section.get("operator_notes")
            or section.get("operator_decision")
            or section.get("operator_confidence")
        ):
            return True
    return False


def _guess_food_service_job(job) -> bool:
    phase1 = job.phase1_results or {}
    inventory = (phase1.get("source_inventory") or {}).get("files") or []
    if any(str(item.get("domain") or "").replace("-", "_") == "food_service" for item in inventory):
        return True
    strategy_files = (phase1.get("strategy_map") or {}).get("files") or {}
    for row in strategy_files.values():
        values = [
            row.get("strategy_id"),
            row.get("source_shape"),
            row.get("primary_target"),
            *(row.get("secondary_targets") or []),
        ]
        if any(str(value or "").startswith("food_service.") for value in values):
            return True
    context = f"{job.client_context or ''}".lower()
    return "food service" in context or "food-service" in context


_SECTION_BUNDLE_KEYS = (
    "meals",
    "recipes",
    "ingredients",
    "suppliers",
    "supplies",
    "orders",
    "prep_tasks",
    "dietary_restrictions",
)

_REGISTER_BUNDLE_KEYS = {
    "meals": "meals",
    "recipes": "recipes",
    "ingredients": "ingredients",
    "suppliers": "suppliers",
    "supplies": "supplies",
    "orders": "orders",
    "prep-tasks": "prep_tasks",
    "dietary-restrictions": "dietary_restrictions",
}


def _safe_cache_part(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-._")
    return cleaned[:120] or "source"


def _section_bundle_cache_path(codex_root: Path, job_id: str, filename: str, section_id: str) -> Path:
    return (
        codex_root
        / "CONTENT"
        / "ingest"
        / "section-bundles"
        / str(job_id)
        / _safe_cache_part(filename)
        / f"{_safe_cache_part(section_id)}.bundle.json"
    )


def _empty_section_bundle() -> dict:
    return {
        "confidence": "low",
        "warnings": [],
        **{key: [] for key in _SECTION_BUNDLE_KEYS},
    }


def _normalize_section_bundle(bundle: dict | None) -> dict:
    if not isinstance(bundle, dict):
        return _empty_section_bundle()
    normalized = _empty_section_bundle()
    confidence = str(bundle.get("confidence") or "medium").lower()
    normalized["confidence"] = confidence if confidence in {"high", "medium", "low", "blocked"} else "medium"
    warnings = bundle.get("warnings") or []
    normalized["warnings"] = [str(item) for item in warnings if str(item).strip()] if isinstance(warnings, list) else []
    for key in _SECTION_BUNDLE_KEYS:
        value = bundle.get(key) or []
        normalized[key] = value if isinstance(value, list) else []
    return normalized


def _read_section_bundle_cache(
    codex_root: Path,
    job_id: str,
    filename: str,
    section_id: str,
) -> tuple[dict | None, Path]:
    cache_path = _section_bundle_cache_path(codex_root, job_id, filename, section_id)
    if not cache_path.exists():
        return None, cache_path
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("[catalyst-materialize] invalid section bundle cache: %s", cache_path)
        return None, cache_path
    if (
        payload.get("source_job_id") != str(job_id)
        or payload.get("source_file") != filename
        or payload.get("section_id") != section_id
    ):
        logger.warning("[catalyst-materialize] stale section bundle cache ignored: %s", cache_path)
        return None, cache_path
    return _normalize_section_bundle(payload.get("bundle")), cache_path


def _write_section_bundle_cache(
    cache_path: Path,
    *,
    job_id: str,
    filename: str,
    section: dict,
    operator_review: str,
    bundle: dict,
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    section_id = str(section.get("section_id") or "section")
    section_title = str(section.get("title") or section_id)
    normalized = _normalize_section_bundle(bundle)
    cache_path.write_text(
        json.dumps(
            {
                "source_job_id": str(job_id),
                "source_file": filename,
                "section_id": section_id,
                "section_title": section_title,
                "operator_review": operator_review,
                "source_locator": {
                    "source_file": filename,
                    "section_id": section_id,
                    "section_title": section_title,
                    "merged_section_ids": section.get("merged_section_ids") or [section_id],
                    "merged_titles": section.get("merged_titles") or [section_title],
                    "start_char": section.get("start_char"),
                    "end_char": section.get("end_char"),
                },
                "bundle": normalized,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


def _bundle_entities_for_register(bundle: dict, register_slug: str) -> list[dict]:
    key = _REGISTER_BUNDLE_KEYS.get(register_slug)
    if not key:
        return []
    entities = bundle.get(key) or []
    return entities if isinstance(entities, list) else []


@shared_task(
    name="catalyst.tasks.materialize_register_entities",
    bind=True,
    max_retries=1,
    default_retry_delay=30,
    soft_time_limit=1800,
    time_limit=1860,
)
def materialize_register_entities(self, group_slug: str, register_slug: str, job_id: str) -> None:
    """
    Phase 3 — extract every named entity from the source files for one register,
    format as markdown, and write into the register's _index.md body.

    Triggered via POST /registers/{slug}/materialize/ after the user has confirmed
    and is in browse mode. Uses extract_entities_chunked() to handle long flat files.
    """
    from catalyst.models import CatalystParseJob
    from catalyst.services.parse_service import (
        extract_entities_from_text,
        extract_food_service_section_bundle,
        extract_entities_chunked,
        format_entity_as_entry_markdown,
        format_entities_as_index_markdown,
        slugify,
    )

    logger.info("[catalyst-materialize] start: group=%s register=%s job=%s", group_slug, register_slug, job_id)

    try:
        job = CatalystParseJob.objects.get(pk=job_id)
    except CatalystParseJob.DoesNotExist:
        logger.error("[catalyst-materialize] job %s not found", job_id)
        return

    codex_root = Path(settings.CATALYST_CODEX_ROOT) / group_slug
    index_path = codex_root / "CONTENT" / "registers" / register_slug / "_index.md"
    if not index_path.exists():
        logger.error("[catalyst-materialize] _index.md not found at %s", index_path)
        return

    fm = _fm_from_index(index_path)
    source_file_str = str(fm.get("source_file", ""))
    display_name = register_slug.replace("-", " ").title()

    # Derive entity type from slug: "recipes" → "recipe", "partners-suppliers" → "partner"
    entity_plural = register_slug.replace("-", " ")
    entity_type = entity_plural.rstrip("s") if entity_plural.endswith("s") else entity_plural

    all_entities: list[dict] = []
    seen_names: set[str] = set()
    reg_dir = codex_root / "CONTENT" / "registers" / register_slug
    progress_path = reg_dir / "_materialization_progress.json"
    progress: dict = {}
    completed_files: set[str] = set()
    file_results: dict[str, dict] = {}
    source_files = _materialization_source_files(job, source_file_str, register_slug)
    logger.warning(
        "[catalyst-materialize] EXTRACTION STARTED group=%s register=%s job=%s source_files=%d",
        group_slug,
        register_slug,
        job_id,
        len(source_files),
    )
    logger.info(
        "[catalyst-materialize] source files for %s/%s: %s",
        group_slug,
        register_slug,
        ", ".join(source_files) if source_files else "(none)",
    )

    def write_progress(current_file: str | None = None, status: str = "running") -> None:
        progress_path.write_text(
            json.dumps(
                {
                    "source_job_id": str(job.pk),
                    "register": register_slug,
                    "status": status,
                    "current_file": current_file,
                    "source_files": source_files,
                    "completed_files": sorted(completed_files),
                    "file_results": file_results,
                    "entry_count": len(all_entities),
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )

    if progress_path.exists():
        try:
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            progress = {}
        if progress.get("source_job_id") == str(job.pk):
            completed_files = set(progress.get("completed_files") or [])
            existing_file_results = progress.get("file_results") or {}
            if isinstance(existing_file_results, dict):
                file_results = existing_file_results
        else:
            progress = {}

    write_progress(status="starting")

    run_as_user, preflight_error = _runtime_preflight(job.group, str(codex_root))
    if preflight_error:
        logger.warning(
            "[catalyst-materialize] Pre-flight failed for group=%s register=%s job=%s: %s",
            group_slug, register_slug, job_id, preflight_error,
        )
        write_progress(status="failed_preflight")
        return

    if progress:
        for sidecar_path in sorted(reg_dir.glob("*.entity.json")):
            try:
                payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if payload.get("source_job_id") != str(job.pk):
                continue
            entity = payload.get("entity")
            if not isinstance(entity, dict):
                continue
            key = entity.get("name", "").lower().strip()
            if key and key not in seen_names:
                seen_names.add(key)
                all_entities.append(entity)
        logger.info(
            "[catalyst-materialize] resuming job=%s register=%s completed_files=%d existing_entities=%d",
            job.pk,
            register_slug,
            len(completed_files),
            len(all_entities),
        )

    def write_materialized_entries(current_file: str | None = None) -> list[str]:
        """Flush current cumulative materialization results to Codex files."""
        entry_slugs: list[str] = []
        seen_slugs: set[str] = set()
        for entity in all_entities:
            raw_slug = slugify(entity.get("name", "unknown"))
            unique_slug = raw_slug
            counter = 2
            while unique_slug in seen_slugs:
                unique_slug = f"{raw_slug}-{counter}"
                counter += 1
            seen_slugs.add(unique_slug)
            entry_slugs.append(unique_slug)

            entry_path = reg_dir / f"{unique_slug}.md"
            entity_sidecar_name = f"{unique_slug}.entity.json"
            source_locator = entity.get("source_locator") if isinstance(entity.get("source_locator"), dict) else None
            source_file = source_locator.get("source_file") if source_locator else source_file_str
            entry_fm_data = {
                "id": str(uuid.uuid4()),
                "register": register_slug,
                "slug": unique_slug,
                "title": str(entity.get("name", "")),
                "status": "draft",
                "source_job_id": str(job.pk),
                "source_file": source_file,
                "source_locator": source_locator,
                "extracted_entity": entity_sidecar_name,
            }
            if entity.get("shape_id"):
                entry_fm_data["shape_id"] = entity.get("shape_id")
            if entity.get("shape_version"):
                entry_fm_data["shape_version"] = entity.get("shape_version")
            entry_fm = "---\n" + yaml.safe_dump(
                entry_fm_data,
                sort_keys=False,
                allow_unicode=True,
            ) + "---\n\n"
            entry_body = format_entity_as_entry_markdown(entity)
            entry_path.write_text(entry_fm + entry_body, encoding="utf-8")

            entity_sidecar_path = reg_dir / entity_sidecar_name
            entity_sidecar_path.write_text(
                json.dumps(
                    {
                        "source_job_id": str(job.pk),
                        "register": register_slug,
                        "slug": unique_slug,
                        "entity": entity,
                    },
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )

        index_body = (
            f"# {display_name}\n\n"
            f"**Source:** {source_file_str}  \n"
            f"**Entries:** {len(all_entities)}\n\n"
            f"## Entries\n\n"
            f"{format_entities_as_index_markdown(entity_plural, all_entities, entry_slugs)}"
        )
        _rewrite_register_body(index_path, index_body)
        logger.info(
            "[catalyst-materialize] flushed %d %s entries to %s",
            len(all_entities),
            entity_plural,
            reg_dir,
        )
        write_progress(current_file=current_file)
        return entry_slugs

    for fname in source_files:
        if fname in completed_files:
            prior = file_results.get(fname) or {}
            logger.info(
                "[catalyst-materialize] skipping completed source file: %s status=%s entity_count=%s",
                fname,
                prior.get("status"),
                prior.get("entity_count"),
            )
            continue
        file_path = job.job_dir() / fname
        if not file_path.exists():
            logger.warning("[catalyst-materialize] source file not found: %s", file_path)
            file_results[fname] = {"status": "missing", "entity_count": 0}
            write_progress(current_file=fname)
            continue
        data = file_path.read_bytes()
        reviewed_sections = _reviewed_sections_for_materialization(job, fname, register_slug)
        has_operator_review = _has_operator_reviewed_sections(job, fname)
        if reviewed_sections:
            logger.warning(
                "[catalyst-materialize] SECTION-DIRECTED EXTRACTION STARTED entity=%s file=%s sections=%d",
                entity_plural,
                fname,
                len(reviewed_sections),
            )
            file_results[fname] = {
                "status": "section_running",
                "extraction_mode": "section_bundle",
                "entity_count": 0,
                "sections_total": len(reviewed_sections),
                "sections_complete": 0,
                "bytes": len(data),
            }
            write_progress(current_file=fname)
            file_added_count = 0
            for section in reviewed_sections:
                section_id = str(section.get("section_id") or "section")
                section_title = str(section.get("title") or section_id)
                section_key = f"{fname}#{section_id}"
                if section_key in completed_files:
                    prior = file_results.get(section_key) or {}
                    logger.info(
                        "[catalyst-materialize] skipping completed section: %s status=%s entity_count=%s",
                        section_key,
                        prior.get("status"),
                        prior.get("entity_count"),
                    )
                    continue
                section_text = str(section.get("content_markdown") or "").strip()
                operator_notes = str(section.get("operator_notes") or "").strip()
                operator_label = str(section.get("operator_label") or section.get("proposed_label") or "").strip()
                operator_review = "\n".join(
                    part for part in [
                        f"Operator label: {operator_label}" if operator_label else "",
                        f"Operator decision: {section.get('operator_decision') or 'review'}",
                        f"Operator confidence: {section.get('operator_confidence')}" if section.get("operator_confidence") else "",
                        operator_notes,
                    ]
                    if part
                )
                logger.warning(
                    "[catalyst-materialize] EXTRACTION SECTION STARTED entity=%s section=%s title=%s chars=%d",
                    entity_plural,
                    section_key,
                    section_title,
                    len(section_text),
                )
                cached_bundle = None
                cache_path = None
                if _guess_food_service_job(job):
                    cached_bundle, cache_path = _read_section_bundle_cache(
                        codex_root,
                        str(job.pk),
                        fname,
                        section_id,
                    )
                file_results[section_key] = {
                    "status": "running",
                    "extraction_mode": "section_bundle",
                    "entity_count": 0,
                    "title": section_title,
                    "content_chars": len(section_text),
                }
                if cache_path:
                    file_results[section_key]["bundle_cache"] = str(cache_path.relative_to(codex_root))
                if cached_bundle:
                    file_results[section_key]["status"] = "cache_hit"
                    file_results[section_key]["bundle"] = {
                        key: len(value) if isinstance(value, list) else 0
                        for key, value in cached_bundle.items()
                        if key in _SECTION_BUNDLE_KEYS
                    }
                    file_results[section_key]["bundle_confidence"] = cached_bundle.get("confidence")
                    file_results[section_key]["bundle_warnings"] = cached_bundle.get("warnings") or []
                write_progress(current_file=section_key)
                try:
                    if _guess_food_service_job(job):
                        bundle = cached_bundle
                        if bundle is None:
                            bundle = extract_food_service_section_bundle(
                                fname,
                                section_id,
                                section_title,
                                section_text,
                                operator_review,
                                codex_cwd=str(codex_root),
                                client_context=job.client_context or None,
                                timeout=180,
                                run_as_user=run_as_user,
                            )
                            if cache_path is None:
                                cache_path = _section_bundle_cache_path(codex_root, str(job.pk), fname, section_id)
                            _write_section_bundle_cache(
                                cache_path,
                                job_id=str(job.pk),
                                filename=fname,
                                section=section,
                                operator_review=operator_review,
                                bundle=bundle,
                            )
                            logger.info(
                                "[catalyst-materialize] section bundle cached: %s",
                                cache_path.relative_to(codex_root),
                            )
                        file_results[section_key]["bundle"] = {
                            key: len(value) if isinstance(value, list) else 0
                            for key, value in bundle.items()
                            if key in _SECTION_BUNDLE_KEYS
                        }
                        file_results[section_key]["bundle_confidence"] = bundle.get("confidence")
                        file_results[section_key]["bundle_warnings"] = bundle.get("warnings") or []
                        if cache_path:
                            file_results[section_key]["bundle_cache"] = str(cache_path.relative_to(codex_root))
                        entities = _bundle_entities_for_register(bundle, register_slug)
                    else:
                        section_context = "\n\n".join(
                            part for part in [
                                job.client_context or "",
                                (
                                    "Use the operator notes as high-priority guidance. "
                                    "Extract only entities supported by this section.\n"
                                    f"Source file: {fname}\n"
                                    f"Section id: {section_id}\n"
                                    f"Section title: {section_title}\n"
                                    f"{operator_review}"
                                ),
                            ]
                            if part.strip()
                        )
                        entities = extract_entities_from_text(
                            f"{fname}#{section_id}",
                            section_text,
                            entity_type=entity_type,
                            entity_plural=entity_plural,
                            codex_cwd=str(codex_root),
                            client_context=section_context or None,
                            timeout=180,
                            run_as_user=run_as_user,
                        )
                except Exception:
                    logger.exception(
                        "[catalyst-materialize] section extraction failed for group=%s register=%s job=%s section=%s",
                        group_slug,
                        register_slug,
                        job_id,
                        section_key,
                    )
                    file_results[section_key] = {
                        "status": "failed",
                        "entity_count": 0,
                        "title": section_title,
                        "content_chars": len(section_text),
                    }
                    write_progress(current_file=section_key)
                    continue

                before_count = len(all_entities)
                for entity in entities:
                    locator = entity.get("source_locator") if isinstance(entity.get("source_locator"), dict) else {}
                    locator.update({
                        "source_file": fname,
                        "section_id": section_id,
                        "section_title": section_title,
                    })
                    entity["source_locator"] = locator
                    key = entity.get("name", "").lower().strip()
                    if key and key not in seen_names:
                        seen_names.add(key)
                        all_entities.append(entity)
                added_count = len(all_entities) - before_count
                file_added_count += added_count
                section_result = dict(file_results.get(section_key) or {})
                section_result.update({
                    "status": "complete" if added_count else "no_entities_found",
                    "entity_count": added_count,
                    "raw_entity_count": len(entities),
                    "title": section_title,
                    "content_chars": len(section_text),
                })
                file_results[section_key] = section_result
                completed_files.add(section_key)
                file_results[fname]["sections_complete"] = int(file_results[fname].get("sections_complete") or 0) + 1
                file_results[fname]["entity_count"] = file_added_count
                write_materialized_entries(current_file=section_key)

            file_results[fname]["status"] = "complete" if file_added_count else "no_entities_found"
            completed_files.add(fname)
            write_materialized_entries(current_file=fname)
            continue

        if has_operator_review:
            logger.warning(
                "[catalyst-materialize] curated fallback blocked — job=%s register=%s file=%s reason=no_matching_reviewed_sections",
                job_id,
                register_slug,
                fname,
            )
            file_results[fname] = {
                "status": "blocked_curated_no_sections",
                "extraction_mode": "blocked",
                "entity_count": 0,
                "bytes": len(data),
                "reason": (
                    "This file has operator section review, but no reviewed sections matched "
                    f"the {register_slug} register. Whole-file extraction was skipped to avoid "
                    "spending tokens against a curated source."
                ),
            }
            completed_files.add(fname)
            write_progress(current_file=fname)
            continue

        phase2_file_result = {}
        if isinstance(job.phase2_results, dict):
            phase2_file_result = (job.phase2_results.get("files") or {}).get(fname) or {}
        try:
            phase2_count = int(phase2_file_result.get("count"))
        except (TypeError, ValueError):
            phase2_count = None
        if phase2_count == 0:
            logger.info(
                "[catalyst-materialize] skipping zero-yield file from Phase 2 — job=%s register=%s file=%s",
                job_id,
                register_slug,
                fname,
            )
            file_results[fname] = {
                "status": "skipped_zero_yield",
                "extraction_mode": "phase2_zero_skip",
                "entity_count": 0,
                "bytes": len(data),
                "reason": "Phase 2 found zero relevant entities and no operator section review exists for this file.",
            }
            completed_files.add(fname)
            write_progress(current_file=fname)
            continue

        logger.warning(
            "[catalyst-materialize] EXTRACTION FILE STARTED entity=%s file=%s bytes=%d",
            entity_plural,
            fname,
            len(data),
        )
        file_results[fname] = {
            "status": "running",
            "extraction_mode": "whole_file_chunked",
            "entity_count": 0,
            "bytes": len(data),
            "token_posture": "spending_tokens",
        }
        write_progress(current_file=fname)
        try:
            section_brief = _operator_section_brief(job, fname)
            extraction_context_parts = [job.client_context or ""]
            if section_brief:
                extraction_context_parts.append(
                    "OPERATOR SECTION REVIEW:\n"
                    "Use this saved human review to target extraction and preserve yields, "
                    "ingredient scopes, meal containers, and ignore/misc decisions.\n"
                    f"{section_brief}"
                )
            entities = extract_entities_chunked(
                fname,
                data,
                entity_type=entity_type,
                entity_plural=entity_plural,
                codex_cwd=str(codex_root),
                client_context="\n\n".join(part for part in extraction_context_parts if part.strip()) or None,
                timeout_per_chunk=180,
                claude_session_id=None,  # one-shot per chunk avoids unbounded batch-session context
                run_as_user=run_as_user,
            )
        except Exception:
            logger.exception(
                "[catalyst-materialize] extraction failed for group=%s register=%s job=%s file=%s",
                group_slug,
                register_slug,
                job_id,
                fname,
            )
            file_results[fname] = {"status": "failed", "entity_count": 0, "bytes": len(data)}
            write_progress(current_file=fname)
            continue
        logger.info(
            "[catalyst-materialize] %d %s extracted from %s",
            len(entities),
            entity_plural,
            fname,
        )
        before_count = len(all_entities)
        for e in entities:
            key = e.get("name", "").lower().strip()
            if key and key not in seen_names:
                seen_names.add(key)
                all_entities.append(e)
        added_count = len(all_entities) - before_count
        file_results[fname] = {
            "status": "complete" if added_count else "no_entities_found",
            "extraction_mode": "whole_file_chunked",
            "entity_count": added_count,
            "raw_entity_count": len(entities),
            "bytes": len(data),
        }
        completed_files.add(fname)
        write_materialized_entries(current_file=fname)

    logger.info("[catalyst-materialize] %d %s extracted across %d files", len(all_entities), entity_plural, len(source_files))
    write_progress(current_file=None, status="complete")

    try:
        _git_codex(codex_root, "add", f"CONTENT/registers/{register_slug}/")
        bundle_cache_root = codex_root / "CONTENT" / "ingest" / "section-bundles" / str(job.pk)
        if bundle_cache_root.exists():
            _git_codex(codex_root, "add", f"CONTENT/ingest/section-bundles/{job.pk}/")
        _git_codex(
            codex_root, "commit", "-m",
            f"materialize: {len(all_entities)} {entity_plural} in {register_slug}",
        )
        logger.info("[catalyst-materialize] committed %d entry files for %s", len(all_entities), register_slug)
    except RuntimeError as exc:
        logger.warning("[catalyst-materialize] git commit failed (non-fatal): %s", exc)
