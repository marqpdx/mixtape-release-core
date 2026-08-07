# catalyst/tasks.py
"""
Celery tasks for the catalyst app.
Route: push queue (Celery-only; must not be consumed by Uvicorn).
"""

import logging

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


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

    url_template = getattr(settings, "CATALYST_TENANT_URL_TEMPLATE", "https://{slug}.crossroads.place/catalyst")
    workspace_url = url_template.format(slug=group.slug)
    contact_name = prospect.primary_contact_name or prospect.name

    context = {
        "contact_name": contact_name,
        "org_name": prospect.name,
        "group_slug": group.slug,
        "workspace_url": workspace_url,
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
