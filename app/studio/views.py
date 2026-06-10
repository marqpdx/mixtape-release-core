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
from recurring_action.models import RecurringAction, RecurrencePattern

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


def _build_beryl_prompt(user):
    """
    Return a BerylPrompt dict if Signal 1 conditions are met, else None.
    Signal 1: 2+ raw Scrap records older than 4h, created after last_surfaced_at.
    Degrades gracefully if beryl or scrap apps are not yet installed.
    """
    try:
        from profiles.models import UserProfile
        profile = UserProfile.objects.get(user=user)
    except Exception:
        return None

    try:
        from beryl.models import BerylState
        beryl_state = BerylState.objects.filter(profile=profile).first()
    except Exception:
        return None

    if beryl_state:
        now = timezone.now()
        # Suppress: remind_later still active
        if (
            beryl_state.dismiss_mode == "remind_later"
            and beryl_state.remind_later_at
            and now < beryl_state.remind_later_at
        ):
            return None
        # Suppress: session-dismissed within the last 8 hours
        if (
            beryl_state.dismiss_mode == "session"
            and beryl_state.last_dismissed_at
            and (now - beryl_state.last_dismissed_at) < timedelta(hours=8)
        ):
            return None

    try:
        from scrap.models import Scrap
        from django.contrib.contenttypes.models import ContentType as CT
        from profiles.models import UserProfile as UP
        profile_ct = CT.objects.get_for_model(UP)
        cutoff = timezone.now() - timedelta(hours=4)
        qs = Scrap.objects.filter(
            content_type=profile_ct,
            owner_object_id=profile.pk,
            status="raw",
            created_at__lte=cutoff,
        )
        if beryl_state and beryl_state.last_surfaced_at:
            qs = qs.filter(created_at__gt=beryl_state.last_surfaced_at)
        count = qs.count()
    except Exception:
        return None

    if count < 2:
        return None

    return {
        "message": f"You have {count} unreviewed captures waiting.",
        "action_label": "Review now",
        "action_context": f"signal:aperture_log:count:{count}",
        "dismissible": True,
    }


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

        # Due RecurringActions for this member (member-owned + group-owned for their groups)
        now = timezone.now()
        personal_due_actions = []
        try:
            from profiles.models import UserProfile
            profile = UserProfile.objects.get(user=user)
            profile_ct = ContentType.objects.get_for_model(UserProfile)

            member_due = RecurringAction.objects.filter(
                content_type=profile_ct,
                owner_object_id=profile.pk,
                is_active=True,
                next_due_at__lte=now,
            ).order_by("next_due_at")[:10]
            personal_due_actions += [
                {**_serialize_recurring_action(r), "owner_type": "member", "group_slug": None}
                for r in member_due
            ]

            # Build a slug lookup for groups this user belongs to
            group_slug_by_id = {str(m.group.pk): m.group.slug for m in memberships}
            group_due = RecurringAction.objects.filter(
                content_type=group_ct,
                owner_object_id__in=group_ids,
                is_active=True,
                next_due_at__lte=now,
            ).order_by("next_due_at")[:10]
            personal_due_actions += [
                {
                    **_serialize_recurring_action(r),
                    "owner_type": "group",
                    "group_slug": group_slug_by_id.get(str(r.owner_object_id)),
                }
                for r in group_due
            ]
        except Exception:
            pass

        return Response({
            "activity": [_serialize_action(a) for a in activity],
            "my_content": my_content,
            "beryl_prompt": _build_beryl_prompt(user),
            "recurring_actions": personal_due_actions,
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

        now = timezone.now()
        since_7d = now - timedelta(days=7)
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

        # RecurringActions: due or overdue within next 48h
        upcoming_cutoff = now + timedelta(hours=48)
        due_actions = RecurringAction.objects.filter(
            content_type=group_ct,
            owner_object_id=group.pk,
            is_active=True,
            next_due_at__lte=upcoming_cutoff,
        ).order_by("next_due_at")[:5]

        recurring_actions = [
            {
                "id": str(r.id),
                "title": r.title,
                "description": r.description,
                "recurrence_rule": r.recurrence_rule,
                "next_due_at": r.next_due_at.isoformat(),
                "last_triggered_at": r.last_triggered_at.isoformat() if r.last_triggered_at else None,
                "suggested_verb": r.suggested_verb,
                "suggested_label": r.suggested_label,
                "is_overdue": r.next_due_at <= now,
            }
            for r in due_actions
        ]

        return Response({
            "metrics": {
                "active_threads": active_threads,
                "pending_approvals": pending_approvals,
                "new_members": new_members,
                "loom_ops_in_flight": loom_ops_in_flight,
            },
            "activity": [_serialize_action(a) for a in activity],
            "recurring_actions": recurring_actions,
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


# ---------------------------------------------------------------------------
# Beryl session helpers
# ---------------------------------------------------------------------------

def _serialize_scrap(s):
    return {
        "id": str(s.id),
        "body": s.body,
        "intent_tag": s.intent_tag,
        "labels": s.labels,
        "status": s.status,
        "remind_at": s.remind_at.isoformat() if s.remind_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


# ---------------------------------------------------------------------------
# Beryl dismiss
# ---------------------------------------------------------------------------

class BerylDismissView(generics.GenericAPIView):
    """POST /api/studio/personal/beryl/dismiss — update BerylState dismiss mode."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        mode = request.data.get("mode")
        if mode not in ("session", "permanent", "remind_later"):
            return Response({"detail": "Invalid mode."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from profiles.models import UserProfile
            from beryl.models import BerylState
            profile = UserProfile.objects.get(user=request.user)
            beryl_state, _ = BerylState.objects.get_or_create(profile=profile)
        except Exception:
            return Response({"detail": "BerylState unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        now = timezone.now()
        beryl_state.last_dismissed_at = now
        beryl_state.dismiss_mode = mode

        if mode == "permanent":
            beryl_state.last_surfaced_at = now
        elif mode == "remind_later":
            beryl_state.remind_later_at = now + timedelta(hours=24)

        beryl_state.save()
        return Response({"status": "ok"})


# ---------------------------------------------------------------------------
# Beryl session surface
# ---------------------------------------------------------------------------

class BerylSessionView(generics.GenericAPIView):
    """
    GET /api/studio/beryl/session?ctx=<action_context>
    Returns raw Scrap records for the member (>4h old, post-last_surfaced_at).
    The ctx param is opaque — used for future signal routing; currently ignored
    beyond being echoed back so the client can correlate the session.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        ctx = request.query_params.get("ctx", "")

        try:
            from profiles.models import UserProfile
            from scrap.models import Scrap
            from django.contrib.contenttypes.models import ContentType as CT
            from beryl.models import BerylState

            profile = UserProfile.objects.get(user=request.user)
            profile_ct = CT.objects.get_for_model(UserProfile)
            cutoff = timezone.now() - timedelta(hours=4)

            qs = Scrap.objects.filter(
                content_type=profile_ct,
                owner_object_id=profile.pk,
                status="raw",
                created_at__lte=cutoff,
            )

            beryl_state = BerylState.objects.filter(profile=profile).first()
            if beryl_state and beryl_state.last_surfaced_at:
                qs = qs.filter(created_at__gt=beryl_state.last_surfaced_at)

            scraps = qs.order_by("intent_tag", "-created_at")[:20]
        except Exception:
            return Response({"detail": "Session unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response({
            "scraps": [_serialize_scrap(s) for s in scraps],
            "context": ctx,
        })


class BerylScrapView(generics.GenericAPIView):
    """
    PATCH /api/studio/beryl/scraps/<pk>
    Update a Scrap within a Beryl session: re-tag, add labels, archive, set remind_at.
    Any mutation transitions status to 'reviewed' unless explicitly archiving.
    """
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk):
        try:
            from profiles.models import UserProfile
            from scrap.models import Scrap, IntentTag, ScrapStatus, RemindStatus
            from django.contrib.contenttypes.models import ContentType as CT

            profile = UserProfile.objects.get(user=request.user)
            profile_ct = CT.objects.get_for_model(UserProfile)
            scrap = get_object_or_404(
                Scrap,
                pk=pk,
                content_type=profile_ct,
                owner_object_id=profile.pk,
            )
        except Scrap.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception:
            return Response({"detail": "Unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        acted = False

        if "intent_tag" in request.data:
            tag = request.data["intent_tag"]
            if tag not in IntentTag.values:
                return Response(
                    {"detail": f"intent_tag must be one of: {', '.join(IntentTag.values)}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            scrap.intent_tag = tag
            acted = True

        if "labels" in request.data:
            labels = request.data["labels"]
            if not isinstance(labels, list) or len(labels) > 10:
                return Response(
                    {"detail": "labels must be a list of up to 10 strings."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            scrap.labels = [str(lbl)[:64] for lbl in labels]
            acted = True

        if "remind_at" in request.data:
            from django.utils.dateparse import parse_datetime
            ra = parse_datetime(request.data["remind_at"] or "")
            if ra:
                scrap.remind_at = ra
                scrap.remind_status = RemindStatus.PENDING
                acted = True

        explicit_status = request.data.get("status")
        if explicit_status == "archived":
            scrap.status = ScrapStatus.ARCHIVED
        elif acted:
            scrap.status = ScrapStatus.REVIEWED

        scrap.save()
        return Response(_serialize_scrap(scrap))


# ---------------------------------------------------------------------------
# RecurringAction — group admin CRUD
# ---------------------------------------------------------------------------

def _serialize_recurring_action(r):
    return {
        "id": str(r.id),
        "title": r.title,
        "description": r.description,
        "recurrence_rule": r.recurrence_rule,
        "next_due_at": r.next_due_at.isoformat(),
        "last_triggered_at": r.last_triggered_at.isoformat() if r.last_triggered_at else None,
        "suggested_verb": r.suggested_verb,
        "suggested_label": r.suggested_label,
        "is_active": r.is_active,
    }


class GroupRecurringActionsView(generics.GenericAPIView):
    """
    GET  /api/studio/groups/<slug>/recurring-actions — list active actions for group
    POST /api/studio/groups/<slug>/recurring-actions — create new action
    Admin or superadmin only.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        group = get_object_or_404(Group, slug=slug, is_active=True)
        denied = _require_group_admin(group, request.user)
        if denied:
            return denied

        group_ct = ContentType.objects.get_for_model(Group)
        actions = RecurringAction.objects.filter(
            content_type=group_ct,
            owner_object_id=group.pk,
            is_active=True,
        ).order_by("next_due_at")

        return Response([_serialize_recurring_action(r) for r in actions])

    def post(self, request, slug):
        group = get_object_or_404(Group, slug=slug, is_active=True)
        denied = _require_group_admin(group, request.user)
        if denied:
            return denied

        title = (request.data.get("title") or "").strip()
        if not title:
            return Response({"detail": "title is required."}, status=status.HTTP_400_BAD_REQUEST)

        recurrence_rule = request.data.get("recurrence_rule", "")
        if recurrence_rule not in RecurrencePattern.values:
            return Response(
                {"detail": f"recurrence_rule must be one of: {', '.join(RecurrencePattern.values)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from django.utils.dateparse import parse_datetime
        next_due_at = parse_datetime(request.data.get("next_due_at", "") or "")
        if not next_due_at:
            return Response({"detail": "next_due_at must be a valid ISO datetime."}, status=status.HTTP_400_BAD_REQUEST)

        group_ct = ContentType.objects.get_for_model(Group)
        action = RecurringAction.objects.create(
            content_type=group_ct,
            owner_object_id=group.pk,
            title=title,
            description=(request.data.get("description") or "").strip(),
            recurrence_rule=recurrence_rule,
            next_due_at=next_due_at,
            suggested_verb=(request.data.get("suggested_verb") or "").strip(),
            suggested_label=(request.data.get("suggested_label") or "").strip(),
        )

        return Response(_serialize_recurring_action(action), status=status.HTTP_201_CREATED)


class GroupRecurringActionDetailView(generics.GenericAPIView):
    """
    PATCH  /api/studio/groups/<slug>/recurring-actions/<pk> — update fields
    DELETE /api/studio/groups/<slug>/recurring-actions/<pk> — soft-delete (is_active=False)
    Admin or superadmin only.
    """
    permission_classes = [permissions.IsAuthenticated]

    def _get_action(self, slug, pk):
        group = get_object_or_404(Group, slug=slug, is_active=True)
        group_ct = ContentType.objects.get_for_model(Group)
        action = get_object_or_404(
            RecurringAction,
            pk=pk,
            content_type=group_ct,
            owner_object_id=group.pk,
        )
        return group, action

    def patch(self, request, slug, pk):
        group, action = self._get_action(slug, pk)
        denied = _require_group_admin(group, request.user)
        if denied:
            return denied

        updatable = ("title", "description", "suggested_verb", "suggested_label")
        for field in updatable:
            if field in request.data:
                setattr(action, field, (request.data[field] or "").strip())

        if "recurrence_rule" in request.data:
            rr = request.data["recurrence_rule"]
            if rr not in RecurrencePattern.values:
                return Response(
                    {"detail": f"recurrence_rule must be one of: {', '.join(RecurrencePattern.values)}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            action.recurrence_rule = rr

        if "next_due_at" in request.data:
            from django.utils.dateparse import parse_datetime
            nda = parse_datetime(request.data["next_due_at"] or "")
            if not nda:
                return Response({"detail": "next_due_at must be a valid ISO datetime."}, status=status.HTTP_400_BAD_REQUEST)
            action.next_due_at = nda

        action.save()
        return Response(_serialize_recurring_action(action))

    def delete(self, request, slug, pk):
        group, action = self._get_action(slug, pk)
        denied = _require_group_admin(group, request.user)
        if denied:
            return denied

        action.is_active = False
        action.save(update_fields=["is_active", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# RecurringAction — personal (member-owned) CRUD  [RA-5]
# ---------------------------------------------------------------------------

class PersonalRecurringActionsView(generics.GenericAPIView):
    """
    GET  /api/studio/personal/recurring-actions — list active member-owned actions
    POST /api/studio/personal/recurring-actions — create new member-owned action
    """
    permission_classes = [permissions.IsAuthenticated]

    def _get_profile(self, user):
        from profiles.models import UserProfile
        return UserProfile.objects.get(user=user)

    def get(self, request):
        try:
            profile = self._get_profile(request.user)
        except Exception:
            return Response({"detail": "Profile not found."}, status=status.HTTP_404_NOT_FOUND)

        profile_ct = ContentType.objects.get_for_model(profile)
        actions = RecurringAction.objects.filter(
            content_type=profile_ct,
            owner_object_id=profile.pk,
            is_active=True,
        ).order_by("next_due_at")

        return Response([_serialize_recurring_action(r) for r in actions])

    def post(self, request):
        try:
            profile = self._get_profile(request.user)
        except Exception:
            return Response({"detail": "Profile not found."}, status=status.HTTP_404_NOT_FOUND)

        title = (request.data.get("title") or "").strip()
        if not title:
            return Response({"detail": "title is required."}, status=status.HTTP_400_BAD_REQUEST)

        recurrence_rule = request.data.get("recurrence_rule", "")
        if recurrence_rule not in RecurrencePattern.values:
            return Response(
                {"detail": f"recurrence_rule must be one of: {', '.join(RecurrencePattern.values)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from django.utils.dateparse import parse_datetime
        next_due_at = parse_datetime(request.data.get("next_due_at", "") or "")
        if not next_due_at:
            return Response({"detail": "next_due_at must be a valid ISO datetime."}, status=status.HTTP_400_BAD_REQUEST)

        profile_ct = ContentType.objects.get_for_model(profile)
        action = RecurringAction.objects.create(
            content_type=profile_ct,
            owner_object_id=profile.pk,
            title=title,
            description=(request.data.get("description") or "").strip(),
            recurrence_rule=recurrence_rule,
            next_due_at=next_due_at,
            suggested_verb=(request.data.get("suggested_verb") or "").strip(),
            suggested_label=(request.data.get("suggested_label") or "").strip(),
        )

        return Response(_serialize_recurring_action(action), status=status.HTTP_201_CREATED)


class PersonalRecurringActionDetailView(generics.GenericAPIView):
    """
    PATCH  /api/studio/personal/recurring-actions/<pk> — update fields
    DELETE /api/studio/personal/recurring-actions/<pk> — soft-delete (is_active=False)
    """
    permission_classes = [permissions.IsAuthenticated]

    def _get_action(self, user, pk):
        from profiles.models import UserProfile
        profile = UserProfile.objects.get(user=user)
        profile_ct = ContentType.objects.get_for_model(profile)
        action = get_object_or_404(
            RecurringAction,
            pk=pk,
            content_type=profile_ct,
            owner_object_id=profile.pk,
        )
        return action

    def patch(self, request, pk):
        try:
            action = self._get_action(request.user, pk)
        except Exception:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        updatable = ("title", "description", "suggested_verb", "suggested_label")
        for field in updatable:
            if field in request.data:
                setattr(action, field, (request.data[field] or "").strip())

        if "recurrence_rule" in request.data:
            rr = request.data["recurrence_rule"]
            if rr not in RecurrencePattern.values:
                return Response(
                    {"detail": f"recurrence_rule must be one of: {', '.join(RecurrencePattern.values)}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            action.recurrence_rule = rr

        if "next_due_at" in request.data:
            from django.utils.dateparse import parse_datetime
            nda = parse_datetime(request.data["next_due_at"] or "")
            if not nda:
                return Response({"detail": "next_due_at must be a valid ISO datetime."}, status=status.HTTP_400_BAD_REQUEST)
            action.next_due_at = nda

        action.save()
        return Response(_serialize_recurring_action(action))

    def delete(self, request, pk):
        try:
            action = self._get_action(request.user, pk)
        except Exception:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        action.is_active = False
        action.save(update_fields=["is_active", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)
