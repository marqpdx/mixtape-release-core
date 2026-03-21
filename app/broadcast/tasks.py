# broadcast/tasks.py
from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def dispatch_broadcast_email_task(self, broadcast_id: str) -> None:
    """
    Send broadcast email via a Listmonk campaign.

    Flow:
      1. Resolve email-opted-in recipients from the broadcast audience.
      2. Create a dedicated, private Listmonk list for this broadcast.
      3. Ensure each recipient exists as a Listmonk subscriber (get-or-create)
         and add them to the list.
      4. Create a Listmonk campaign with the broadcast body inlined as HTML.
      5. Set campaign status → "running" to dispatch.
      6. Bulk-create BroadcastDelivery rows (status=sent) for the steward report.
      7. Store the Listmonk campaign ID on the broadcast record.

    Idempotent: if lm_campaign_id is already set the task returns immediately.
    """
    from broadcast.models import BroadcastDelivery, GroupBroadcast
    from broadcast.services.broadcast_service import _resolve_recipients, _user_allows

    try:
        broadcast = (
            GroupBroadcast.objects
            .select_related("group", "created_by")
            .get(pk=broadcast_id)
        )
    except GroupBroadcast.DoesNotExist:
        logger.warning("dispatch_broadcast_email_task: broadcast %s not found", broadcast_id)
        return

    if broadcast.lm_campaign_id:
        logger.info("broadcast_email_already_sent broadcast=%s campaign=%s", broadcast_id, broadcast.lm_campaign_id)
        return

    recipients = _resolve_recipients(broadcast)
    email_recipients = [
        u for u in recipients
        if _user_allows(u, broadcast.group, "email") and u.email
    ]

    if not email_recipients:
        logger.info("broadcast_email_no_recipients broadcast=%s", broadcast_id)
        return

    from lanternmail.services.listmonk_client import get_listmonk_client

    client = get_listmonk_client()
    group = broadcast.group
    group_title = str(getattr(group, "title", group.slug))

    # 1. Create a dedicated ephemeral list for this broadcast
    list_resp = client.create_list(
        name=f"broadcast:{broadcast.pk}",
        list_type="private",
        optin="single",
        tags=["broadcast", f"group:{group.slug}"],
        description=f"{broadcast.title[:100]} — {group_title}",
    )
    lm_list_id = list_resp["data"]["id"]

    # 2. Subscribe each recipient (get-or-create in Listmonk)
    subscribed_users = []
    for user in email_recipients:
        lm_sub_id = _get_or_create_listmonk_subscriber(client, user)
        if lm_sub_id is None:
            logger.warning("broadcast_email_skip_subscriber broadcast=%s user=%s", broadcast_id, user.pk)
            continue
        try:
            client.update_subscriber_lists(
                subscriber_id=lm_sub_id,
                add=[lm_list_id],
                status="confirmed",
            )
            subscribed_users.append(user)
        except Exception as exc:
            logger.warning(
                "broadcast_email_subscribe_failed broadcast=%s user=%s error=%s",
                broadcast_id, user.pk, exc,
            )

    if not subscribed_users:
        logger.warning("broadcast_email_no_subscribers broadcast=%s — no users subscribed to list", broadcast_id)
        return

    # 3. Create campaign with inlined content
    subject = f"[{group_title}] {broadcast.title}"
    campaign_resp = client.create_campaign(
        name=f"broadcast:{broadcast.pk}",
        subject=subject,
        list_ids=[lm_list_id],
        body=_build_campaign_body(broadcast, group_title),
        content_type="html",
        messenger="email",
        tags=["broadcast", f"group:{group.slug}", broadcast.priority],
    )
    lm_campaign_id = str(campaign_resp["data"]["id"])

    # 4. Run the campaign
    client.update_campaign_status(int(lm_campaign_id), "running")

    # 5. Bulk-create delivery receipts for the steward report
    now = timezone.now()
    BroadcastDelivery.objects.bulk_create(
        [
            BroadcastDelivery(
                broadcast=broadcast,
                user=u,
                channel=BroadcastDelivery.Channel.EMAIL,
                status=BroadcastDelivery.DeliveryStatus.SENT,
                sent_at=now,
            )
            for u in subscribed_users
        ],
        ignore_conflicts=True,
    )

    # 6. Store campaign ID on broadcast
    GroupBroadcast.objects.filter(pk=broadcast.pk).update(lm_campaign_id=lm_campaign_id)

    logger.info(
        "broadcast_email_campaign_sent broadcast=%s campaign=%s recipients=%d",
        broadcast_id, lm_campaign_id, len(subscribed_users),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_or_create_listmonk_subscriber(client, user) -> int | None:
    """
    Return the Listmonk subscriber ID for the user's email.
    Searches first; creates if not found. Returns None on failure.
    """
    from lanternmail.services.exceptions import ListmonkError

    display_name = (
        f"{user.first_name} {user.last_name}".strip()
        or user.username
        or user.email
    )

    # Search by exact email
    try:
        res = client.search_subscribers(query=f"subscribers.email = '{user.email}'", per_page=1)
        results = res.get("data", {}).get("results") or []
        if results:
            return results[0]["id"]
    except ListmonkError as exc:
        logger.warning("broadcast_email_search_subscriber failed email=%s error=%s", user.email, exc)

    # Not found — create
    try:
        res = client.create_subscriber(
            email=user.email,
            name=display_name,
            status="enabled",
        )
        return res["data"]["id"]
    except ListmonkError as exc:
        logger.error("broadcast_email_create_subscriber failed email=%s error=%s", user.email, exc)
        return None


def _build_campaign_body(broadcast, group_title: str) -> str:
    """Build a minimal HTML body for the Listmonk campaign."""
    import html as html_lib

    title = html_lib.escape(broadcast.title)
    body = html_lib.escape(broadcast.body).replace("\n", "<br>")
    group = html_lib.escape(group_title)
    priority = broadcast.priority

    priority_note = ""
    if priority in ("important", "urgent"):
        priority_note = f'<p style="color:#b45309;font-weight:bold;">Priority: {html_lib.escape(priority.upper())}</p>'

    return f"""
<div style="font-family:sans-serif;max-width:600px;margin:0 auto">
  {priority_note}
  <h2 style="margin-top:0">{title}</h2>
  <p style="white-space:pre-wrap">{body}</p>
  <hr style="margin:24px 0;border:none;border-top:1px solid #e5e7eb">
  <p style="color:#6b7280;font-size:13px">Sent by {group} via Mixtape</p>
</div>
""".strip()


@shared_task
def dispatch_scheduled_broadcasts_task() -> None:
    """
    Celery beat task — runs every 60 seconds.
    Finds queued broadcasts with scheduled_at <= now and dispatches them.
    """
    from broadcast.models import GroupBroadcast
    from broadcast.services.broadcast_service import send_broadcast

    due = (
        GroupBroadcast.objects
        .filter(
            status=GroupBroadcast.Status.QUEUED,
            scheduled_at__isnull=False,
            scheduled_at__lte=timezone.now(),
        )
        .select_related("group", "created_by")
    )

    for broadcast in due:
        try:
            send_broadcast(broadcast)
            logger.info("broadcast_scheduled_dispatched broadcast=%s", broadcast.pk)
        except Exception as exc:
            logger.error("broadcast_scheduled_failed broadcast=%s error=%s", broadcast.pk, exc)
