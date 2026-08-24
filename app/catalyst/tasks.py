# catalyst/tasks.py
"""
Celery tasks for the catalyst app.
Route: push queue (Celery-only; must not be consumed by Uvicorn).
"""

import logging
import subprocess
import urllib.parse
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

    try:
        job = CatalystParseJob.objects.get(pk=job_id)
    except CatalystParseJob.DoesNotExist:
        logger.error("[catalyst-parse] Job %s not found — aborting task for %s", job_id, filename)
        return

    file_path = job.job_dir() / filename
    if not file_path.exists():
        logger.error("[catalyst-parse] File %s not found on disk for job %s", filename, job_id)
        ai_result: dict = {"error": "file not found on disk", "count": 0}
    else:
        data = file_path.read_bytes()
        logger.info("[catalyst-parse] Analyzing %s (job=%s)", filename, job_id)
        try:
            ai = semantic_analyze(
                filename,
                data,
                codex_cwd=None,
                client_context=job.client_context or None,
                timeout=210,
            )
            ai_result = ai if ai is not None else {"count": 0, "notes": "timed out or skipped"}
        except Exception as exc:
            logger.exception("[catalyst-parse] semantic_analyze failed for %s", filename)
            ai_result = {"error": str(exc), "count": 0}

    # Atomically update phase2_results
    with transaction.atomic():
        job_fresh = CatalystParseJob.objects.select_for_update().get(pk=job_id)
        p2 = job_fresh.phase2_results or {}
        files_dict: dict = p2.get("files", {})
        files_dict[filename] = ai_result
        p2["files"] = files_dict
        job_fresh.phase2_results = p2
        job_fresh.save(update_fields=["phase2_results"])
        files_done = len(files_dict)
        files_total = len(job_fresh.uploaded_files)

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
    from catalyst.services.parse_service import slugify

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
                if not ai or ai.get("count", 0) == 0:
                    continue
                ai_slug = slugify(ai.get("entity_type", "records"))
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
                        "display_name": ai.get("entity_plural", ai.get("entity_type", "records")).title(),
                        "entry_count": ai["count"],
                        "source_file": filename,
                        "canon_synonym": "Canon",
                        "notes": ai_notes,
                        "confidence": ai.get("confidence", "medium"),
                        "columns": [],
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


@shared_task(
    name="catalyst.tasks.materialize_register_entities",
    bind=True,
    max_retries=1,
    default_retry_delay=30,
    soft_time_limit=600,
    time_limit=660,
)
def materialize_register_entities(self, group_slug: str, register_slug: str, job_id: str) -> None:
    """
    Phase 3 — extract every named entity from the source files for one register,
    format as markdown, and write into the register's _index.md body.

    Triggered via POST /registers/{slug}/materialize/ after the user has confirmed
    and is in browse mode. Uses extract_entities_chunked() to handle long flat files.
    """
    from catalyst.models import CatalystParseJob
    from catalyst.services.parse_service import extract_entities_chunked, format_entities_as_markdown

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

    source_files = [s.strip() for s in source_file_str.split(",") if s.strip()]
    if not source_files:
        # Fall back: try all uploaded files
        source_files = [f["filename"] for f in (job.uploaded_files or [])]

    all_entities: list[dict] = []
    seen_names: set[str] = set()

    for fname in source_files:
        file_path = job.job_dir() / fname
        if not file_path.exists():
            logger.warning("[catalyst-materialize] source file not found: %s", file_path)
            continue
        data = file_path.read_bytes()
        entities = extract_entities_chunked(
            fname,
            data,
            entity_type=entity_type,
            entity_plural=entity_plural,
            client_context=job.client_context or None,
            timeout_per_chunk=180,
        )
        for e in entities:
            key = e.get("name", "").lower().strip()
            if key and key not in seen_names:
                seen_names.add(key)
                all_entities.append(e)

    logger.info("[catalyst-materialize] %d %s extracted across %d files", len(all_entities), entity_plural, len(source_files))

    entries_md = format_entities_as_markdown(entity_plural, all_entities)
    body = (
        f"# {display_name}\n\n"
        f"**Source:** {source_file_str}\n\n"
        f"**Entries extracted:** {len(all_entities)}\n\n"
        f"## Entries\n\n"
        f"{entries_md}"
    )

    _rewrite_register_body(index_path, body)

    try:
        _git_codex(codex_root, "add", f"CONTENT/registers/{register_slug}/_index.md")
        _git_codex(
            codex_root, "commit", "-m",
            f"materialize: {len(all_entities)} {entity_plural} in {register_slug}",
        )
        logger.info("[catalyst-materialize] committed %s", register_slug)
    except RuntimeError as exc:
        logger.warning("[catalyst-materialize] git commit failed (non-fatal): %s", exc)
