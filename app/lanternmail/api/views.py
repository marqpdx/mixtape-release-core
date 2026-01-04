# lanternmail/api/views.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from groups.models import Group
from lanternmail.models import LanternmailList

from lanternmail.services.listmonk_client import get_listmonk_client
from lanternmail.api.utils import send_listmonk_invitations

from lanternmail.services.lanternmail_service import LanternmailService
from lanternmail.services.exceptions import (
    ListmonkAuthError,
    ListmonkBadRequestError,
    ListmonkNotFoundError,
    ListmonkUpstreamError,
)

User = get_user_model()


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
    user_lists = (
        LanternmailList.objects.filter(group__members=request.user, is_active=True)
        .select_related("group")
        .order_by("-created_at")
    )

    return Response({"data": [_serialize_list(lst) for lst in user_lists]})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_mailing_list_detail(request, list_id: int) -> Response:
    """
    Get details of a specific mailing list including Listmonk stats.
    Returns Django record even if Listmonk is temporarily unavailable.
    """
    mailing_list = get_object_or_404(LanternmailList, id=list_id)

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
def toggle_mailing_list(request, list_id: int) -> Response:
    """Toggle active status of a mailing list (Django-side)."""
    mailing_list = get_object_or_404(LanternmailList, id=list_id, group__members=request.user)

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
            resp = lm.search_subscribers(query=user.email)
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
    mailing_lists = LanternmailList.objects.filter(group=group, is_active=True).order_by("created_at")

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
            resp = lm.search_subscribers(query=user.email)
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
# Invitations
# -----------------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def send_list_invitations(request, list_id: int) -> Response:
    """
    Send invitation emails to subscribe to a mailing list.

    This currently uses `send_listmonk_invitations` util. You can later promote this
    into LanternmailService as well, but this keeps your working path intact.
    """
    mailing_list = get_object_or_404(LanternmailList, id=list_id)
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
