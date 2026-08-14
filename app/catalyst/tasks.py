# catalyst/tasks.py
"""
Celery tasks for the catalyst app.
Route: push queue (Celery-only; must not be consumed by Uvicorn).
"""

import logging
import urllib.parse

from celery import shared_task
from django.conf import settings

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
    url_template = getattr(settings, "CATALYST_TENANT_URL_TEMPLATE", "https://{slug}.crossroads.place/app/groups/{slug}/catalyst")
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

    url_template = getattr(settings, "CATALYST_TENANT_URL_TEMPLATE", "https://{slug}.crossroads.place/app/groups/{slug}/catalyst")
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
