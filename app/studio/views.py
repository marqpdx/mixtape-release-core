# studio/views.py

from collections import defaultdict
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response

from activity.models import Action
from groups.models import Group, GroupMembership
from groups.services.groups import GroupService
from initiatives.models import ActionRun, ActionRunStatus

User = get_user_model()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_group_admin(group, user):
    """True if user is admin, steward, or owner in the group."""
    membership = GroupService.get_user_membership(group, user)
    return bool(membership and (membership.is_admin() or membership.is_steward()))


def _require_group_admin(group, user):
    """Return a 403 Response if the user is not an admin/steward/superadmin; None otherwise."""
    if user.is_staff:
        return None
    if not _is_group_admin(group, user):
        return Response({"detail": "Group admin or superadmin required."}, status=status.HTTP_403_FORBIDDEN)
    return None


def _membership_role(membership):
    if membership.is_admin() or membership.is_steward():
        return "admin"
    return "member"


def _serialize_action(action):
    return {
        "id": str(action.id),
        "verb": action.verb,
        "summary": action.metadata.get("summary", ""),
        "group_slug": action.metadata.get("group_slug", ""),
        "timestamp": action.created_at.isoformat() if action.created_at else None,
    }


def _group_library(group):
    """Return the puddlejump Library for this group, or None."""
    try:
        from puddlejump.models import Library
        group_ct = ContentType.objects.get_for_model(Group)
        return Library.objects.filter(
            owner_content_type=group_ct,
            owner_object_id=group.pk,
        ).first()
    except Exception:
        return None


def _action_runs_for_group(group):
    """Base queryset: ActionRuns scoped to this group's tenant_id."""
    return ActionRun.objects.filter(tenant_id=group.pk)


# ---------------------------------------------------------------------------
# Personal Studio
# ---------------------------------------------------------------------------

class PersonalStudioView(generics.GenericAPIView):
    """
    GET /api/studio/personal
    Aggregated activity feed + personal content list for the requesting user.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        user_ct = ContentType.objects.get_for_model(User)

        # Groups this user belongs to
        memberships = GroupMembership.objects.filter(
            member_content_type=user_ct,
            member_object_id=user.pk,
            is_active=True,
        ).select_related("group")

        group_ids = [str(m.group.pk) for m in memberships]
        group_ct = ContentType.objects.get_for_model(Group)

        # Recent activity across those groups (context = group)
        activity = (
            Action.objects
            .filter(
                context_content_type=group_ct,
                context_id__in=group_ids,
            )
            .order_by("-created_at")[:20]
        )

        # Personal writing content
        my_content = []
        try:
            from writing.models import WritingPiece
            pieces = (
                WritingPiece.objects
                .filter(author=user)
                .order_by("-updated_at")[:10]
            )
            my_content = [
                {
                    "id": str(p.pk),
                    "title": p.title or "Untitled",
                    "status": getattr(p, "status", "draft"),
                    "updated_at": p.updated_at.isoformat() if p.updated_at else None,
                }
                for p in pieces
            ]
        except Exception:
            pass

        return Response({
            "activity": [_serialize_action(a) for a in activity],
            "my_content": my_content,
        })


class PersonalGroupsView(generics.GenericAPIView):
    """
    GET /api/studio/personal/groups
    User's group list with per-group unread/pending counts.
    Separate from /api/activity/group-pulse (boolean flags); this returns counts.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        user_ct = ContentType.objects.get_for_model(User)

        memberships = (
            GroupMembership.objects
            .filter(
                member_content_type=user_ct,
                member_object_id=user.pk,
                is_active=True,
            )
            .select_related("group")
            .order_by("group__title")
        )

        result = [
            {
                "slug": m.group.slug,
                "name": m.group.title,
                "role": _membership_role(m),
                "unread_count": 0,   # placeholder — own notification system not yet wired
                "pending_count": 0,  # placeholder — pending actions not yet aggregated per user
            }
            for m in memberships
            if m.group.is_active
        ]

        return Response(result)


# ---------------------------------------------------------------------------
# Group Studio — Pulse
# ---------------------------------------------------------------------------

class GroupPulseView(generics.GenericAPIView):
    """
    GET /api/studio/groups/<slug>/pulse
    Metric strip + activity feed for a group. Admin or superadmin only.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        group = get_object_or_404(Group, slug=slug, is_active=True)
        denied = _require_group_admin(group, request.user)
        if denied:
            return denied

        since_7d = timezone.now() - timedelta(days=7)
        user_ct = ContentType.objects.get_for_model(User)
        group_ct = ContentType.objects.get_for_model(Group)

        action_runs = _action_runs_for_group(group)

        # Metric: new members in last 7 days
        new_members = GroupMembership.objects.filter(
            group=group,
            member_content_type=user_ct,
            created_at__gte=since_7d,
            is_active=True,
        ).count()

        # Metric: Loom ops in flight
        loom_ops_in_flight = action_runs.filter(status=ActionRunStatus.RUNNING).count()

        # Metric: pending approvals (cloud-eligible ops awaiting consent)
        pending_approvals = action_runs.filter(
            status=ActionRunStatus.PENDING,
            cloud_approved=False,
        ).count()

        # Metric: active threads — Forum objects sponsored by this group
        active_threads = 0
        try:
            from threadworks.models import Forum
            active_threads = Forum.objects.filter(
                sponsor_content_type=group_ct,
                sponsor_object_id=str(group.pk),
                is_archived=False,
            ).count()
        except Exception:
            pass

        # Activity feed: Actions where context is this group
        activity = (
            Action.objects
            .filter(context_content_type=group_ct, context_id=str(group.pk))
            .order_by("-created_at")[:20]
        )

        return Response({
            "metrics": {
                "active_threads": active_threads,
                "pending_approvals": pending_approvals,
                "new_members": new_members,
                "loom_ops_in_flight": loom_ops_in_flight,
            },
            "activity": [_serialize_action(a) for a in activity],
        })


# ---------------------------------------------------------------------------
# Group Studio — Canon
# ---------------------------------------------------------------------------

class GroupCanonView(generics.GenericAPIView):
    """
    GET /api/studio/groups/<slug>/canon
    Doc counts by status + recently updated list + library summary by path.
    Admin or superadmin only. Returns empty structure if Puddlejump inactive.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        group = get_object_or_404(Group, slug=slug, is_active=True)
        denied = _require_group_admin(group, request.user)
        if denied:
            return denied

        empty = {
            "metrics": {"canon": 0, "working": 0, "needs_review": 0, "stale": 0},
            "recently_updated": [],
            "library_by_path": [],
        }

        library = _group_library(group)
        if not library:
            return Response(empty)

        stale_cutoff = timezone.now() - timedelta(days=90)
        items = library.items.filter(is_folder=False).order_by("-updated_at")

        # Status counts — LibraryItem has no canonization status field yet.
        # Stale = not updated in 90+ days. All others counted as working until
        # the governance status field is added in a future migration.
        stale_count = items.filter(updated_at__lt=stale_cutoff).count()
        total_count = items.count()
        working_count = total_count - stale_count

        recently_updated = [
            {
                "id": str(item.pk),
                "title": item.title or item.filename or "Untitled",
                "folder_path": item.folder_path,
                "status": "stale" if item.updated_at and item.updated_at < stale_cutoff else "working",
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            }
            for item in items[:10]
        ]

        # Group by folder_path for the library tree
        path_counts = defaultdict(int)
        for item in items:
            path = item.folder_path or "/"
            path_counts[path] += 1

        library_by_path = [
            {"path": path, "doc_count": count}
            for path, count in sorted(path_counts.items())
        ]

        return Response({
            "metrics": {
                "canon": 0,         # populated once governance status field exists
                "working": working_count,
                "needs_review": 0,  # populated once governance status field exists
                "stale": stale_count,
            },
            "recently_updated": recently_updated,
            "library_by_path": library_by_path,
        })


# ---------------------------------------------------------------------------
# Group Studio — Command
# ---------------------------------------------------------------------------

class GroupCommandView(generics.GenericAPIView):
    """
    GET /api/studio/groups/<slug>/command
    Loom metrics + active ops list. Admin or superadmin only.
    Returns empty structure if no Loom-eligible work area active.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        group = get_object_or_404(Group, slug=slug, is_active=True)
        denied = _require_group_admin(group, request.user)
        if denied:
            return denied

        action_runs = _action_runs_for_group(group)

        ops_in_flight = action_runs.filter(status=ActionRunStatus.RUNNING).count()
        awaiting_approval = action_runs.filter(
            status=ActionRunStatus.PENDING,
            cloud_approved=False,
        ).count()

        active_ops_qs = (
            action_runs
            .filter(status__in=[ActionRunStatus.RUNNING, ActionRunStatus.PENDING])
            .order_by("-created_at")[:20]
        )

        active_ops = [
            {
                "id": str(run.pk),
                "tool_name": run.tool_name,
                "verb": run.tool_name.split(".")[-1] if "." in run.tool_name else run.tool_name,
                "description": (run.request_payload or {}).get("description", ""),
                "execution_mode": run.execution_mode,
                "status": run.status,
                "created_at": run.created_at.isoformat() if run.created_at else None,
            }
            for run in active_ops_qs
        ]

        return Response({
            "metrics": {
                "ops_in_flight": ops_in_flight,
                "awaiting_approval": awaiting_approval,
                "schema_pass_rate": None,  # not yet computed
            },
            "active_ops": active_ops,
        })


# ---------------------------------------------------------------------------
# Group Studio — Clients (staff only)
# ---------------------------------------------------------------------------

class GroupClientsView(generics.GenericAPIView):
    """
    GET /api/studio/groups/<slug>/clients
    Prospect pipeline + client record for this group. is_staff only — 403 for all others.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        if not request.user.is_staff:
            return Response({"detail": "Staff access required."}, status=status.HTTP_403_FORBIDDEN)

        group = get_object_or_404(Group, slug=slug, is_active=True)

        try:
            from business.models import Client
            client = Client.objects.select_related("prospect").get(group=group)
            client_data = {
                "id": str(client.pk),
                "group_slug": group.slug,
                "group_title": group.title,
                "primary_contact_name": getattr(client, "primary_contact_name", ""),
                "primary_contact_email": getattr(client, "primary_contact_email", ""),
                "primary_contact_phone": getattr(client, "primary_contact_phone", ""),
                "website": getattr(client, "website", ""),
                "business_type": getattr(client, "business_type", ""),
                "prospect_slug": client.prospect.slug if client.prospect else None,
                "created_at": client.created_at.isoformat() if client.created_at else None,
            }
        except Exception:
            client_data = None

        prospect_data = None
        try:
            from prospects.models import BusinessProspect
            prospect = BusinessProspect.objects.filter(group=group).first()
            if prospect:
                prospect_data = {
                    "id": str(prospect.pk),
                    "slug": prospect.slug,
                    "stage": getattr(prospect, "stage", ""),
                    "contact_name": getattr(prospect, "contact_name", ""),
                    "contact_email": getattr(prospect, "contact_email", ""),
                }
        except Exception:
            pass

        return Response({
            "client": client_data,
            "prospect": prospect_data,
        })
