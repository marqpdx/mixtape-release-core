# groups/tasks.py
"""
Celery tasks for the groups app.
"""
from __future__ import annotations

import logging
import traceback

from celery import shared_task
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(
    name="groups.tasks.send_invitation_email",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def send_invitation_email(self, invitation_id: int) -> None:
    """
    Send a group invitation email via the Mailjet HTTP API.

    Uses the HTTP API (not SMTP) so we get a real provider_message_id back,
    which enables support debugging and confirms actual acceptance by Mailjet.

    Stores task_id, queued_at, sent_at, provider_message_id, and last_send_error
    on the GroupInvitation row so every send attempt is fully observable.
    """
    from django.conf import settings
    from django.template.loader import render_to_string
    from mailjet_rest import Client

    from groups.models import GroupInvitation
    from groups.models.group import EmailStatus

    now = timezone.now()

    # ── Load invitation ────────────────────────────────────────────────────
    try:
        invitation = GroupInvitation.objects.select_related(
            "group", "invited_by", "invited_user"
        ).get(id=invitation_id)
    except GroupInvitation.DoesNotExist:
        logger.error("[invite-task] Invitation %s not found — aborting", invitation_id)
        return

    logger.info(
        "[invite-task] START invitation=%s email=%s task=%s",
        invitation_id,
        invitation.invited_email,
        self.request.id,
    )

    # Record task ID so it can be cross-referenced with Celery logs
    invitation.last_task_id = self.request.id
    invitation.save(update_fields=["last_task_id"])

    # ── Reconstruct invite URL from InviteLink ─────────────────────────────
    from groups.models.group import InviteLink

    is_existing_user = invitation.invited_user.is_active if invitation.invited_user else False

    invite_link = (
        InviteLink.objects.filter(
            user=invitation.invited_user,
            group=invitation.group,
            is_used=False,
        )
        .order_by("-id")
        .first()
    ) if invitation.invited_user else None

    if invite_link:
        if is_existing_user:
            invite_url = f"{settings.FRONTEND_URL}/app/invitations/accept/{invite_link.shortcode}"
        else:
            invite_url = f"{settings.FRONTEND_URL}/app/invitations/accept/{invite_link.shortcode}/new"
    else:
        invite_url = ""
        logger.warning(
            "[invite-task] No unused InviteLink for invitation=%s — invite_url will be empty",
            invitation_id,
        )

    # ── Build template context ─────────────────────────────────────────────
    context = {
        "group_name": invitation.group.title,
        "invited_by_name": invitation.invited_by.get_full_name() if invitation.invited_by else "",
        "message": invitation.message,
        "invite_url": invite_url,
        "is_existing_user": is_existing_user,
    }

    try:
        text_body = render_to_string("email/invite_to_group.txt", context)
        html_body = render_to_string("email/invite_to_group.html", context)
    except Exception as exc:
        logger.exception("[invite-task] Template render failed for invitation %s", invitation_id)
        invitation.last_send_error = f"Template render error: {exc}"
        invitation.email_status = EmailStatus.FAILED
        invitation.save(update_fields=["last_send_error", "email_status"])
        raise

    # ── Send via Mailjet HTTP API ──────────────────────────────────────────
    from_email, from_name = _parse_from_email(settings.DEFAULT_FROM_EMAIL)

    mailjet = Client(
        auth=(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD),
        version="v3.1",
    )

    payload = {
        "Messages": [
            {
                "From": {"Email": from_email, "Name": from_name},
                "To": [{"Email": invitation.invited_email}],
                "Subject": f"You're invited to join {invitation.group.title}",
                "TextPart": text_body,
                "HTMLPart": html_body,
                "CustomID": f"invitation-{invitation_id}",
            }
        ]
    }

    try:
        response = mailjet.send.create(data=payload)
    except Exception as exc:
        err = f"Mailjet request error: {exc}\n{traceback.format_exc()}"
        logger.exception("[invite-task] Mailjet request failed for invitation %s", invitation_id)
        invitation.last_send_error = err
        invitation.email_status = EmailStatus.FAILED
        invitation.save(update_fields=["last_send_error", "email_status"])
        raise self.retry(exc=exc)

    # ── Parse response ─────────────────────────────────────────────────────
    status_code = response.status_code
    response_json = response.json()

    if status_code != 200:
        err = f"Mailjet HTTP {status_code}: {response_json}"
        logger.error("[invite-task] Mailjet rejected invitation %s — %s", invitation_id, err)
        invitation.last_send_error = err
        invitation.email_status = EmailStatus.FAILED
        invitation.save(update_fields=["last_send_error", "email_status"])
        raise self.retry(exc=Exception(err))

    # Extract MessageID from first message / first recipient
    try:
        message_result = response_json["Messages"][0]
        if message_result.get("Status") != "success":
            err = f"Mailjet message status not success: {message_result}"
            logger.error("[invite-task] %s invitation=%s", err, invitation_id)
            invitation.last_send_error = err
            invitation.email_status = EmailStatus.FAILED
            invitation.save(update_fields=["last_send_error", "email_status"])
            raise self.retry(exc=Exception(err))

        provider_message_id = str(message_result["To"][0]["MessageID"])
    except (KeyError, IndexError, TypeError) as exc:
        logger.warning(
            "[invite-task] Could not extract MessageID for invitation %s: %s",
            invitation_id, exc,
        )
        provider_message_id = None

    # ── Mark sent ──────────────────────────────────────────────────────────
    invitation.email_status = EmailStatus.SENT
    invitation.provider = "mailjet"
    invitation.provider_message_id = provider_message_id
    invitation.last_send_error = None
    invitation.sent_at = now
    invitation.save(update_fields=[
        "email_status", "provider", "provider_message_id",
        "last_send_error", "sent_at",
    ])

    logger.info(
        "[invite-task] SENT invitation=%s email=%s message_id=%s",
        invitation_id,
        invitation.invited_email,
        provider_message_id,
    )


def _parse_from_email(from_email_setting: str) -> tuple[str, str]:
    """
    Parse 'Display Name <email@domain.com>' into (email, name).
    Falls back to (raw_string, "") if no angle-bracket format.
    """
    import re
    match = re.match(r"^(.+?)\s*<(.+?)>\s*$", from_email_setting)
    if match:
        return match.group(2), match.group(1).strip()
    return from_email_setting, ""


@shared_task(bind=True, max_retries=3)
def execute_due_ownership_requests(self):
    """
    Periodic task: find and execute pending ownership requests
    whose delay has expired.

    Uses select_for_update(skip_locked=True) so multiple workers
    won't double-execute the same request.
    """
    from groups.models.ownership import OwnershipChangeRequest, OwnershipRequestStatus
    from groups.services.ownership import execute_ownership_request

    now = timezone.now()

    # Collect IDs under a short lock so we don't hold select_for_update
    # across long-running execute calls.
    with transaction.atomic():
        due_ids = list(
            OwnershipChangeRequest.objects
            .filter(
                status=OwnershipRequestStatus.PENDING,
                execute_after__lte=now,
            )
            .select_for_update(skip_locked=True)
            .values_list("pk", flat=True)
        )

    count = 0
    for request_id in due_ids:
        try:
            request = OwnershipChangeRequest.objects.get(pk=request_id)
            execute_ownership_request(request)
            count += 1
        except Exception:
            logger.exception(
                "Failed to execute ownership request %s", request_id
            )

    if count:
        logger.info("Executed %d ownership change request(s)", count)
