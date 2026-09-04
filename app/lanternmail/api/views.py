# lanternmail/api/views.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from django.conf import settings
import requests
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from django.views.decorators.csrf import csrf_exempt

from groups.models import Group
from groups.models import GroupMembership
from lanternmail.models import LanternmailList, LanternmailPost

from lanternmail.services.listmonk_client import get_listmonk_client
from lanternmail.api.utils import send_listmonk_invitations, build_email_query, build_uuid_query

from lanternmail.services.lanternmail_service import LanternmailService
from lanternmail.services.exceptions import (
    ListmonkError,
    ListmonkAuthError,
    ListmonkBadRequestError,
    ListmonkNotFoundError,
    ListmonkUpstreamError,
)
from lanternmail.api.throttles import NewsletterIPThrottle, NewsletterEmailThrottle

User = get_user_model()


LANTERNMAIL_MANAGER_DECORATOR = "can__ManageLanternmail"


def _get_active_user_membership(user: User, group: Group) -> Optional[GroupMembership]:
    if not user or not user.is_authenticated:
        return None

    user_content_type = ContentType.objects.get_for_model(user)
    return GroupMembership.objects.filter(
        group=group,
        member_content_type=user_content_type,
        member_object_id=user.id,
        is_active=True,
        is_pending=False,
        is_banned=False,
        is_evicted=False,
    ).first()


def _can_manage_lanternmail(user: User, group: Group) -> bool:
    if getattr(user, "is_superuser", False):
        return True

    membership = _get_active_user_membership(user, group)
    if not membership:
        return False

    if membership.is_admin():
        return True

    return LANTERNMAIL_MANAGER_DECORATOR in membership.get_decorator_codes()


def _require_lanternmail_manager(request, group: Group) -> Optional[Response]:
    if _can_manage_lanternmail(request.user, group):
        return None

    return Response(
        {"error": "You do not have permission to manage Lanternmail for this group."},
        status=status.HTTP_403_FORBIDDEN,
    )


def _campaign_belongs_to_group(campaign: Dict[str, Any], group: Group) -> bool:
    group_listmonk_ids = set(
        LanternmailList.objects.filter(group=group, is_active=True).values_list("listmonk_id", flat=True)
    )
    campaign_list_ids = {item.get("id") for item in campaign.get("lists", []) if item.get("id") is not None}
    return bool(group_listmonk_ids.intersection(campaign_list_ids))


# -----------------------------------------------------------------------------
# Error mapping
# -----------------------------------------------------------------------------
def _listmonk_error_response(e: Exception) -> Response:
    if isinstance(e, ListmonkBadRequestError):
        # payload/validation errors (either ours or upstream's validation)
        return Response(
            {"error": "Listmonk request invalid", "detail": str(e)},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if isinstance(e, ListmonkAuthError):
        return Response(
            {"error": "Listmonk auth failed", "detail": str(e)},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    if isinstance(e, ListmonkNotFoundError):
        return Response(
            {"error": "Listmonk resource not found", "detail": str(e)},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    if isinstance(e, ListmonkUpstreamError):
        return Response(
            {"error": "Listmonk upstream error", "detail": str(e)},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    return Response(
        {"error": "Listmonk error", "detail": str(e)},
        status=status.HTTP_502_BAD_GATEWAY,
    )


def _serialize_list(lst: LanternmailList) -> Dict[str, Any]:
    return {
        "id": lst.id,
        "listmonk_id": lst.listmonk_id,
        "display_name": lst.display_name,
        "listmonk_name": lst.listmonk_name,
        "description": lst.description,
        "group_id": str(lst.group.id),
        "group_slug": lst.group.slug,
        "group_title": lst.group.title,
        "listmonk_uuid": lst.listmonk_uuid,
        "created_at": lst.created_at.isoformat() if lst.created_at else None,
        "updated_at": lst.updated_at.isoformat() if lst.updated_at else None,
        "is_active": lst.is_active,
    }


# -----------------------------------------------------------------------------
# Mailing lists
# -----------------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_group_mailing_list(request, slug: str) -> Response:
    """
    Create a mailing list for a specific group.

    Notes:
    - This endpoint is group-scoped to support sponsor = group or member later.
    - Uses LanternmailService + ListmonkClient as the single upstream integration point.
    """
    try:
        group = get_object_or_404(Group, slug=slug)
        permission_error = _require_lanternmail_manager(request, group)
        if permission_error:
            return permission_error

        display_name = request.data.get("name", "").strip()
        list_description = request.data.get("description", "").strip()
        list_type = request.data.get("type", "private")  # private|public
        optin_type = request.data.get("optin", "double")  # single|double

        if not display_name:
            return Response({"error": "List name is required"}, status=status.HTTP_400_BAD_REQUEST)

        existing = LanternmailList.objects.filter(group=group, display_name=display_name).first()
        if existing:
            return Response(
                {
                    "message": "A mailing list with this name already exists for this group",
                    "data": _serialize_list(existing),
                }
            )

        lm = get_listmonk_client()
        svc = LanternmailService(lm=lm)

        try:
            lantern_list = svc.create_group_list(
                group=group,
                display_name=display_name,
                description=list_description,
                list_type=list_type,
                optin=optin_type,
                tags=["lantern-mail", "group", group.slug],
            )
        except (ListmonkBadRequestError, ListmonkAuthError, ListmonkNotFoundError, ListmonkUpstreamError) as e:
            return _listmonk_error_response(e)

        return Response(
            {
                "message": "Mailing list created successfully",
                "data": _serialize_list(lantern_list),
            },
            status=status.HTTP_201_CREATED,
        )

    except IntegrityError:
        # In case svc enforces unique listmonk_name + something raced.
        return Response(
            {"error": "A list with this name already exists in this group"},
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_group_mailing_lists(request, slug: str) -> Response:
    """Get all active mailing lists for a specific group (Django-side truth)."""
    group = get_object_or_404(Group, slug=slug)
    permission_error = _require_lanternmail_manager(request, group)
    if permission_error:
        return permission_error

    group_lists = (
        LanternmailList.objects.filter(group=group, is_active=True)
        .select_related("group")
        .order_by("-created_at")
    )

    return Response(
        {
            "data": [_serialize_list(lst) for lst in group_lists],
            "group": {"id": str(group.id), "title": group.title, "slug": group.slug},
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_user_mailing_lists(request) -> Response:
    """
    Get all mailing lists for groups the user belongs to.

    NOTE: This assumes you have a `group__members` relation. If your membership
    model differs (GenericFK), swap this queryset accordingly.
    """
    user_content_type = ContentType.objects.get_for_model(User)
    group_ids = (
        Group.memberships.through.objects.filter(
            is_active=True,
            is_pending=False,
            is_banned=False,
            is_evicted=False,
            member_content_type=user_content_type,
            member_object_id=request.user.id,
        )
        .values_list("group_id", flat=True)
    )
    user_lists = (
        LanternmailList.objects.filter(group_id__in=group_ids, is_active=True)
        .select_related("group")
        .order_by("-created_at")
    )

    return Response({"data": [_serialize_list(lst) for lst in user_lists]})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_mailing_list_detail(request, slug: str, list_id: int) -> Response:
    """
    Get details of a specific mailing list including Listmonk stats.
    Returns Django record even if Listmonk is temporarily unavailable.
    """
    group = get_object_or_404(Group, slug=slug)
    permission_error = _require_lanternmail_manager(request, group)
    if permission_error:
        return permission_error

    mailing_list = get_object_or_404(LanternmailList, id=list_id, group=group)

    lm = get_listmonk_client()

    listmonk_data: Optional[Dict[str, Any]] = None
    campaign_results: List[Dict[str, Any]] = []

    try:
        listmonk_data = lm.get_list(mailing_list.listmonk_id)["data"]
        campaigns = lm.list_campaigns(list_id=mailing_list.listmonk_id)
        campaign_results = campaigns.get("data", {}).get("results", [])
    except (ListmonkBadRequestError, ListmonkAuthError, ListmonkNotFoundError, ListmonkUpstreamError):
        # degrade gracefully
        listmonk_data = None
        campaign_results = []

    payload = _serialize_list(mailing_list)
    payload.update(
        {
            "subscriber_count": listmonk_data.get("subscriber_count", 0) if listmonk_data else 0,
            "campaign_count": len(campaign_results),
            "status": "enabled" if mailing_list.is_active else "disabled",
        }
    )

    return Response({"data": payload})


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def toggle_mailing_list(request, slug: str, list_id: int) -> Response:
    """Toggle active status of a mailing list (Django-side)."""
    group = get_object_or_404(Group, slug=slug)
    permission_error = _require_lanternmail_manager(request, group)
    if permission_error:
        return permission_error

    mailing_list = get_object_or_404(LanternmailList, id=list_id, group=group)

    mailing_list.is_active = not mailing_list.is_active
    mailing_list.save(update_fields=["is_active"])

    return Response(
        {
            "message": f"Mailing list {'activated' if mailing_list.is_active else 'deactivated'}",
            "data": {"id": mailing_list.id, "is_active": mailing_list.is_active},
        }
    )


# -----------------------------------------------------------------------------
# Subscribers + subscription status
# -----------------------------------------------------------------------------
def _find_exact_email(results: List[Dict[str, Any]], email: str) -> Optional[Dict[str, Any]]:
    email_l = email.lower()
    for s in results:
        if (s.get("email") or "").lower() == email_l:
            return s
    return None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_group_members_with_subscription_status(request, slug: str, list_id: int) -> Response:
    """
    For a given group + list, return members and whether they're subscribed to that list.

    Implementation note:
    - Uses Listmonk search by email per member. This is fine for early scale.
    - If this gets slow later, switch to batching/caching or storing subscriber_id in Django.
    """
    group = get_object_or_404(Group, slug=slug)
    permission_error = _require_lanternmail_manager(request, group)
    if permission_error:
        return permission_error

    mailing_list = get_object_or_404(LanternmailList, id=list_id, group=group)

    user_content_type = ContentType.objects.get_for_model(User)
    user_memberships = group.memberships.filter(
        is_active=True,
        is_pending=False,
        is_banned=False,
        is_evicted=False,
        member_content_type=user_content_type,
    )

    lm = get_listmonk_client()
    members_data: List[Dict[str, Any]] = []

    for membership in user_memberships:
        user = membership.member_object
        if not user:
            continue

        subscription_status = "never_invited"
        invited_at = None

        try:
            resp = lm.search_subscribers(query=build_email_query(user.email))
            results = resp.get("data", {}).get("results", [])
            subscriber = _find_exact_email(results, user.email)

            if subscriber:
                list_subscription = next(
                    (ls for ls in subscriber.get("lists", []) if ls.get("id") == mailing_list.listmonk_id),
                    None,
                )
                if list_subscription:
                    sub_status = list_subscription.get("subscription_status")
                    if sub_status == "confirmed":
                        subscription_status = "subscribed"
                    elif sub_status == "unconfirmed":
                        subscription_status = "pending"
                    elif sub_status == "unsubscribed":
                        subscription_status = "unsubscribed"
                    else:
                        subscription_status = "never_invited"

                    invited_at = list_subscription.get("subscription_created_at")
        except (ListmonkBadRequestError, ListmonkAuthError, ListmonkNotFoundError, ListmonkUpstreamError):
            # degrade: treat as never invited when upstream is unavailable
            subscription_status = "never_invited"
            invited_at = None

        display_name = user.get_full_name() or getattr(user, "username", "") or user.email
        avatar_url = None
        if hasattr(user, "profile") and user.profile:
            display_name = user.profile.display_name or display_name
            if getattr(user.profile, "avatar", None):
                avatar = user.profile.avatar
                avatar_url = avatar.url if hasattr(avatar, "url") else str(avatar)

        members_data.append(
            {
                "id": str(user.id),
                "name": display_name,
                "email": user.email,
                "avatar": avatar_url,
                "subscription_status": subscription_status,
                "invited_at": invited_at,
                "role": getattr(membership, "role", None),
            }
        )

    return Response({"data": members_data})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_group_members_all_lists(request, slug: str) -> Response:
    """
    For a group, return members + subscription breakdown across all active lists for that group.
    """
    group = get_object_or_404(Group, slug=slug)
    permission_error = _require_lanternmail_manager(request, group)
    if permission_error:
        return permission_error

    mailing_lists = LanternmailList.objects.filter(group=group, is_active=True).order_by("created_at")
    list_id_param = request.query_params.get("list_id")
    list_id = int(list_id_param) if list_id_param and list_id_param.isdigit() else None

    user_content_type = ContentType.objects.get_for_model(User)
    user_memberships = group.memberships.filter(
        is_active=True,
        is_pending=False,
        is_banned=False,
        is_evicted=False,
        member_content_type=user_content_type,
    )

    lm = get_listmonk_client()
    members_data: List[Dict[str, Any]] = []

    for membership in user_memberships:
        user = membership.member_object
        if not user:
            continue

        list_subscriptions: Dict[int, Dict[str, Any]] = {}
        overall_status = "never_invited"
        latest_invited_at = None

        try:
            resp = lm.search_subscribers(query=build_email_query(user.email))
            results = resp.get("data", {}).get("results", [])
            subscriber = _find_exact_email(results, user.email)

            if subscriber:
                subscriber_lists = subscriber.get("lists", [])

                for ml in mailing_lists:
                    ls = next((x for x in subscriber_lists if x.get("id") == ml.listmonk_id), None)
                    if not ls:
                        continue

                    sub_status = ls.get("subscription_status")
                    invited_at = ls.get("subscription_created_at")

                    list_subscriptions[ml.id] = {
                        "list_name": ml.display_name,
                        "list_id": ml.id,
                        "listmonk_id": ml.listmonk_id,
                        "status": sub_status,
                        "invited_at": invited_at,
                    }

                    # overall status: confirmed > unconfirmed > unsubscribed > never
                    if sub_status == "confirmed":
                        overall_status = "has_subscriptions"
                    elif sub_status == "unconfirmed" and overall_status not in ("has_subscriptions",):
                        overall_status = "pending"
                    elif sub_status == "unsubscribed" and overall_status == "never_invited":
                        overall_status = "unsubscribed"

                    if invited_at and (latest_invited_at is None or invited_at > latest_invited_at):
                        latest_invited_at = invited_at
        except (ListmonkBadRequestError, ListmonkAuthError, ListmonkNotFoundError, ListmonkUpstreamError):
            list_subscriptions = {}
            overall_status = "never_invited"
            latest_invited_at = None

        if list_id and list_id not in list_subscriptions:
            continue

        display_name = user.get_full_name() or getattr(user, "username", "") or user.email
        if hasattr(user, "profile") and user.profile:
            display_name = user.profile.display_name or display_name

        members_data.append(
            {
                "id": str(user.id),
                "name": display_name,
                "email": user.email,
                "overall_subscription_status": overall_status,
                "latest_invited_at": latest_invited_at,
                "list_subscriptions": list_subscriptions,
                "total_lists": mailing_lists.count(),
                "subscribed_lists_count": len([x for x in list_subscriptions.values() if x.get("status") == "confirmed"]),
                "pending_lists_count": len([x for x in list_subscriptions.values() if x.get("status") == "unconfirmed"]),
                "role": getattr(membership, "role", None),
            }
        )

    return Response(
        {
            "data": members_data,
            "group_info": {
                "id": str(group.id),
                "name": group.title,
                "total_lists": mailing_lists.count(),
                "mailing_lists": [
                    {"id": ml.id, "name": ml.display_name, "listmonk_id": ml.listmonk_id} for ml in mailing_lists
                ],
            },
        }
    )


# -----------------------------------------------------------------------------
# Subscriber removal (list-scoped)
# -----------------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def remove_list_subscriber(request, slug: str, list_id: int) -> Response:
    """
    Remove a subscriber from a specific list (Listmonk).
    Expects: { email: string }
    """
    email = (request.data.get("email") or "").strip().lower()
    if not email:
        return Response({"error": "Email is required"}, status=status.HTTP_400_BAD_REQUEST)

    group = get_object_or_404(Group, slug=slug)
    permission_error = _require_lanternmail_manager(request, group)
    if permission_error:
        return permission_error

    mailing_list = get_object_or_404(LanternmailList, id=list_id, group=group)

    lm = get_listmonk_client()

    try:
        resp = lm.search_subscribers(query=build_email_query(email), per_page=1, page=1)
        results = resp.get("data", {}).get("results", [])
        subscriber = next((s for s in results if (s.get("email") or "").lower() == email), None)
        if not subscriber:
            return Response({"error": "Subscriber not found"}, status=status.HTTP_404_NOT_FOUND)

        subscriber_id = subscriber.get("id")
        if not subscriber_id:
            return Response({"error": "Subscriber not found"}, status=status.HTTP_404_NOT_FOUND)

        lm.update_subscriber_lists(subscriber_id=subscriber_id, remove=[mailing_list.listmonk_id])
    except (ListmonkBadRequestError, ListmonkAuthError, ListmonkNotFoundError, ListmonkUpstreamError) as e:
        return _listmonk_error_response(e)

    return Response({"message": "Subscriber removed from list"}, status=status.HTTP_200_OK)


# -----------------------------------------------------------------------------
# Campaigns
# -----------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_group_campaigns(request, slug: str) -> Response:
    """
    List campaigns for a group. Optional query param: list_id (Django list id).
    """
    group = get_object_or_404(Group, slug=slug)
    permission_error = _require_lanternmail_manager(request, group)
    if permission_error:
        return permission_error

    list_id_param = request.query_params.get("list_id")
    list_id = int(list_id_param) if list_id_param and list_id_param.isdigit() else None

    listmonk_list_id = None
    if list_id:
        mailing_list = get_object_or_404(LanternmailList, id=list_id, group=group)
        listmonk_list_id = mailing_list.listmonk_id

    lm = get_listmonk_client()
    try:
        if listmonk_list_id is not None:
            campaigns = lm.list_campaigns(list_id=listmonk_list_id)
            return Response({"data": campaigns.get("data", {}).get("results", [])})

        results_by_id: Dict[int, Dict[str, Any]] = {}
        for mailing_list in LanternmailList.objects.filter(group=group, is_active=True):
            campaigns = lm.list_campaigns(list_id=mailing_list.listmonk_id)
            for campaign in campaigns.get("data", {}).get("results", []):
                campaign_id = campaign.get("id")
                if campaign_id is not None:
                    results_by_id[campaign_id] = campaign

        return Response({"data": list(results_by_id.values())})
    except (ListmonkBadRequestError, ListmonkAuthError, ListmonkNotFoundError, ListmonkUpstreamError) as e:
        return _listmonk_error_response(e)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_group_campaign(request, slug: str) -> Response:
    """
    Create a draft campaign for a specific list.
    Expects: { list_id, name, subject, body, content_type? }
    """
    group = get_object_or_404(Group, slug=slug)
    permission_error = _require_lanternmail_manager(request, group)
    if permission_error:
        return permission_error

    list_id = request.data.get("list_id")
    name = (request.data.get("name") or "").strip()
    subject = (request.data.get("subject") or "").strip()
    body = (request.data.get("body") or "").strip()
    content_type = request.data.get("content_type") or "richtext"

    if not list_id:
        return Response({"error": "List id is required"}, status=status.HTTP_400_BAD_REQUEST)
    if not name or not subject or not body:
        return Response({"error": "Name, subject, and body are required"}, status=status.HTTP_400_BAD_REQUEST)

    mailing_list = get_object_or_404(LanternmailList, id=list_id, group=group)
    lm = get_listmonk_client()

    try:
        resp = lm.create_campaign(
            name=name,
            subject=subject,
            list_ids=[mailing_list.listmonk_id],
            body=body,
            content_type=content_type,
        )
        return Response({"data": resp.get("data")}, status=status.HTTP_201_CREATED)
    except (ListmonkBadRequestError, ListmonkAuthError, ListmonkNotFoundError, ListmonkUpstreamError) as e:
        return _listmonk_error_response(e)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def test_group_campaign(request, slug: str, campaign_id: int) -> Response:
    """
    Send a test campaign to a list of emails.
    Expects: { emails: string[] }
    """
    emails = request.data.get("emails", [])
    if not emails:
        return Response({"error": "No email addresses provided"}, status=status.HTTP_400_BAD_REQUEST)

    group = get_object_or_404(Group, slug=slug)
    permission_error = _require_lanternmail_manager(request, group)
    if permission_error:
        return permission_error

    lm = get_listmonk_client()
    try:
        campaign = lm.get_campaign(campaign_id).get("data") or {}
        if not _campaign_belongs_to_group(campaign, group):
            return Response({"error": "Campaign not found for this group"}, status=status.HTTP_404_NOT_FOUND)

        resp = lm.test_campaign(campaign_id=campaign_id, subscribers=emails)
        return Response({"data": resp.get("data")})
    except (ListmonkBadRequestError, ListmonkAuthError, ListmonkNotFoundError, ListmonkUpstreamError) as e:
        return _listmonk_error_response(e)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def send_group_campaign(request, slug: str, campaign_id: int) -> Response:
    """
    Send a campaign now (set status to running).
    """
    group = get_object_or_404(Group, slug=slug)
    permission_error = _require_lanternmail_manager(request, group)
    if permission_error:
        return permission_error

    lm = get_listmonk_client()
    try:
        campaign = lm.get_campaign(campaign_id).get("data") or {}
        if not _campaign_belongs_to_group(campaign, group):
            return Response({"error": "Campaign not found for this group"}, status=status.HTTP_404_NOT_FOUND)

        resp = lm.update_campaign_status(campaign_id=campaign_id, status="running")
        return Response({"data": resp.get("data")})
    except (ListmonkBadRequestError, ListmonkAuthError, ListmonkNotFoundError, ListmonkUpstreamError) as e:
        return _listmonk_error_response(e)


# -----------------------------------------------------------------------------
# Invitations
# -----------------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def send_list_invitations(request, slug: str, list_id: int) -> Response:
    """
    Send invitation emails to subscribe to a mailing list.

    This currently uses `send_listmonk_invitations` util. You can later promote this
    into LanternmailService as well, but this keeps your working path intact.
    """
    group = get_object_or_404(Group, slug=slug)
    permission_error = _require_lanternmail_manager(request, group)
    if permission_error:
        return permission_error

    mailing_list = get_object_or_404(LanternmailList, id=list_id, group=group)
    emails = request.data.get("emails", [])

    if not emails:
        return Response({"error": "No email addresses provided"}, status=status.HTTP_400_BAD_REQUEST)

    result = send_listmonk_invitations(
        mailing_list.listmonk_id,
        mailing_list.listmonk_uuid,
        emails,
        mailing_list.display_name,
    )

    if result.get("success"):
        return Response(
            {
                "message": f"Invitations sent to {result['invited_count']} recipients",
                "data": {"invited_count": result["invited_count"], "emails": result["emails"]},
            }
        )

    return Response(
        {"error": result.get("error", "Failed to send invitations"), "detail": result.get("detail")},
        status=status.HTTP_502_BAD_GATEWAY,
    )


# -----------------------------------------------------------------------------
# Public Subscribe
# -----------------------------------------------------------------------------
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([NewsletterIPThrottle, NewsletterEmailThrottle])
@csrf_exempt
def public_subscribe(request) -> Response:
    """
    Public subscribe endpoint for the primary newsletter.
    Expects: { email: string, list_slug: string, website?: string }
    """
    email = request.data.get("email")
    list_slug = request.data.get("list_slug")
    honeypot = request.data.get("website")

    if not email:
        return Response({"error": "Email is required"}, status=status.HTTP_400_BAD_REQUEST)
    if not list_slug:
        return Response({"error": "List slug is required"}, status=status.HTTP_400_BAD_REQUEST)
    if honeypot:
        return Response({"error": "Invalid request"}, status=status.HTTP_400_BAD_REQUEST)

    mailing_list = get_object_or_404(LanternmailList, listmonk_name=list_slug)

    result = send_listmonk_invitations(
        mailing_list.listmonk_id,
        mailing_list.listmonk_uuid,
        [email],
        mailing_list.display_name,
    )

    if result.get("success"):
        return Response(
            {
                "message": "Invitation sent",
                "data": {"invited_count": result.get("invited_count", 1), "emails": [email]},
            }
        )

    return Response(
        {"error": result.get("error", "Failed to subscribe"), "detail": result.get("detail")},
        status=status.HTTP_502_BAD_GATEWAY,
    )


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([])
@csrf_exempt
def public_confirm_subscription(request) -> Response:
    """
    Public confirmation endpoint that proxies Listmonk opt-in.
    Expects query params: uuid, list
    """
    subscriber_uuid = request.query_params.get("uuid")
    list_uuid = request.query_params.get("list")

    if not subscriber_uuid or not list_uuid:
        return Response({"error": "Missing confirmation parameters"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        mailing_list = get_object_or_404(LanternmailList, listmonk_uuid=list_uuid)
        lm = get_listmonk_client()
        resp = lm.search_subscribers(query=build_uuid_query(subscriber_uuid), per_page=1, page=1)
        results = resp.get("data", {}).get("results", [])
        subscriber = next((s for s in results if (s.get("uuid") or "").lower() == subscriber_uuid.lower()), None)
        if not subscriber:
            return Response({"error": "Subscriber not found"}, status=status.HTTP_404_NOT_FOUND)

        subscriber_id = subscriber.get("id")
        if not subscriber_id:
            return Response({"error": "Subscriber not found"}, status=status.HTTP_404_NOT_FOUND)

        lm.update_subscriber_lists(
            subscriber_id=subscriber_id,
            add=[mailing_list.listmonk_id],
            status="confirmed",
        )
        return Response({"message": "Subscription confirmed"}, status=status.HTTP_200_OK)
    except (ListmonkBadRequestError, ListmonkAuthError, ListmonkNotFoundError, ListmonkUpstreamError) as e:
        return _listmonk_error_response(e)


# ============================================================================
# LanternmailPost — Phase 1
# ============================================================================

def _serialize_post(post: LanternmailPost) -> Dict[str, Any]:
    return {
        "id": str(post.id),
        "group": {"id": str(post.group.id), "slug": post.group.slug, "title": post.group.title},
        "created_by": str(post.created_by_id) if post.created_by_id else None,
        "created_by_display": post.created_by.username if post.created_by else None,
        "title": post.title,
        "subject": post.subject,
        "body_json": post.body_json,
        "body_text": post.body_text,
        "status": post.status,
        "audience_kind": post.audience_kind,
        "mailing_list": post.mailing_list_id,
        "listmonk_campaign_id": post.listmonk_campaign_id,
        "sent_at": post.sent_at.isoformat() if post.sent_at else None,
        "ingest_status": post.ingest_status,
        "source_content_type": post.source_content_type_id,
        "source_object_id": post.source_object_id,
        "publication_group": post.publication_group_id,
        "content_placement": post.content_placement_id,
        "metadata": post.metadata,
        "created_at": post.created_at.isoformat() if post.created_at else None,
        "updated_at": post.updated_at.isoformat() if post.updated_at else None,
    }


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def lanternmail_posts_list(request, slug: str) -> Response:
    group = get_object_or_404(Group, slug=slug)

    denied = _require_lanternmail_manager(request, group)
    if denied:
        return denied

    if request.method == "GET":
        posts = LanternmailPost.objects.filter(group=group).select_related(
            "created_by", "group", "mailing_list"
        )
        return Response([_serialize_post(p) for p in posts])

    # POST — create
    data = request.data
    title = (data.get("title") or "").strip()
    subject = (data.get("subject") or "").strip()
    if not title or not subject:
        return Response(
            {"error": "title and subject are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    audience_kind = data.get("audience_kind", LanternmailPost.AUDIENCE_MEMBERS)
    valid_audiences = {c[0] for c in LanternmailPost.AUDIENCE_CHOICES}
    if audience_kind not in valid_audiences:
        return Response(
            {"error": f"Invalid audience_kind. Valid values: {sorted(valid_audiences)}"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    mailing_list = None
    if data.get("mailing_list"):
        mailing_list = LanternmailList.objects.filter(
            id=data["mailing_list"], group=group
        ).first()
        if not mailing_list:
            return Response(
                {"error": "mailing_list not found for this group."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    post = LanternmailPost.objects.create(
        group=group,
        created_by=request.user,
        title=title,
        subject=subject,
        body_json=data.get("body_json", {}),
        audience_kind=audience_kind,
        mailing_list=mailing_list,
        metadata=data.get("metadata", {}),
    )
    return Response(_serialize_post(post), status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def lanternmail_post_detail(request, slug: str, post_id: str) -> Response:
    group = get_object_or_404(Group, slug=slug)

    denied = _require_lanternmail_manager(request, group)
    if denied:
        return denied

    post = get_object_or_404(LanternmailPost, id=post_id, group=group)

    if request.method == "GET":
        return Response(_serialize_post(post))

    if request.method == "DELETE":
        if post.status not in (LanternmailPost.STATUS_DRAFT, LanternmailPost.STATUS_REVIEW):
            return Response(
                {"error": "Only draft or review posts may be deleted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        post.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # PATCH — update
    data = request.data
    updated_fields = []

    if "title" in data:
        title = (data["title"] or "").strip()
        if not title:
            return Response({"error": "title may not be blank."}, status=status.HTTP_400_BAD_REQUEST)
        post.title = title
        updated_fields.append("title")

    if "subject" in data:
        subject = (data["subject"] or "").strip()
        if not subject:
            return Response({"error": "subject may not be blank."}, status=status.HTTP_400_BAD_REQUEST)
        post.subject = subject
        updated_fields.append("subject")

    if "body_json" in data:
        post.body_json = data["body_json"] or {}
        post.body_text = ""  # reset so mixin save re-derives from body_json
        updated_fields.extend(["body_json", "body_text"])

    if "audience_kind" in data:
        valid_audiences = {c[0] for c in LanternmailPost.AUDIENCE_CHOICES}
        if data["audience_kind"] not in valid_audiences:
            return Response(
                {"error": f"Invalid audience_kind. Valid values: {sorted(valid_audiences)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        post.audience_kind = data["audience_kind"]
        updated_fields.append("audience_kind")

    if "mailing_list" in data:
        if data["mailing_list"] is None:
            post.mailing_list = None
        else:
            ml = LanternmailList.objects.filter(id=data["mailing_list"], group=group).first()
            if not ml:
                return Response(
                    {"error": "mailing_list not found for this group."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            post.mailing_list = ml
        updated_fields.append("mailing_list")

    if "metadata" in data:
        if not isinstance(data["metadata"], dict):
            return Response({"error": "metadata must be an object."}, status=status.HTTP_400_BAD_REQUEST)
        post.metadata = data["metadata"]
        updated_fields.append("metadata")

    # Status transition — validated last
    if "status" in data:
        new_status = data["status"]
        if new_status == LanternmailPost.STATUS_SENT:
            return Response(
                {"error": "Transitioning to 'sent' is not available in Phase 1. Use the Listmonk send flow."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not post.can_transition_to(new_status):
            valid = sorted(post.VALID_TRANSITIONS.get(post.status, set()) - {LanternmailPost.STATUS_SENT})
            return Response(
                {
                    "error": f"Invalid status transition from '{post.status}' to '{new_status}'.",
                    "valid_next_statuses": valid,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        post.status = new_status
        updated_fields.append("status")

    if updated_fields:
        post.save(update_fields=updated_fields + ["updated_at"])

    return Response(_serialize_post(post))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def sync_lanternmail_post_campaign(request, slug: str, post_id: str) -> Response:
    group = get_object_or_404(Group, slug=slug)
    denied = _require_lanternmail_manager(request, group)
    if denied:
        return denied

    post = get_object_or_404(
        LanternmailPost.objects.select_related("group", "mailing_list", "created_by"),
        id=post_id,
        group=group,
    )
    svc = LanternmailService(lm=get_listmonk_client())

    try:
        post = svc.create_or_update_post_campaign(post=post)
    except ListmonkError as e:
        return _listmonk_error_response(e)

    return Response({"data": _serialize_post(post)})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def test_lanternmail_post(request, slug: str, post_id: str) -> Response:
    emails = request.data.get("emails", [])
    if not emails:
        return Response({"error": "No email addresses provided"}, status=status.HTTP_400_BAD_REQUEST)
    if not isinstance(emails, list):
        return Response({"error": "emails must be a list."}, status=status.HTTP_400_BAD_REQUEST)

    group = get_object_or_404(Group, slug=slug)
    denied = _require_lanternmail_manager(request, group)
    if denied:
        return denied

    post = get_object_or_404(
        LanternmailPost.objects.select_related("group", "mailing_list", "created_by"),
        id=post_id,
        group=group,
    )
    svc = LanternmailService(lm=get_listmonk_client())

    try:
        post = svc.create_or_update_post_campaign(post=post)
        resp = svc.lm.test_campaign(campaign_id=post.listmonk_campaign_id, subscribers=emails)
    except ListmonkError as e:
        return _listmonk_error_response(e)

    return Response({"data": resp.get("data"), "post": _serialize_post(post)})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def send_lanternmail_post(request, slug: str, post_id: str) -> Response:
    group = get_object_or_404(Group, slug=slug)
    denied = _require_lanternmail_manager(request, group)
    if denied:
        return denied

    post = get_object_or_404(
        LanternmailPost.objects.select_related("group", "mailing_list", "created_by"),
        id=post_id,
        group=group,
    )
    svc = LanternmailService(lm=get_listmonk_client())

    try:
        post = svc.send_post(post=post)
    except ListmonkError as e:
        return _listmonk_error_response(e)

    return Response({"data": _serialize_post(post)})
