import uuid

from django.core.files.storage import default_storage
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from console import services
from console.models import HubCapture, HubCaptureKind, HubCaptureStatus, HubCaptureVisibility
from console.tasks import transcribe_hub_capture_task
from files.models import StoredFile


class ReentryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response({"items": services.get_reentry_items(request.user)})


class SignalsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(services.get_signals(request.user))


class OrientationView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(services.get_orientation(request.user))


class StewardshipView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(services.get_stewardship(request.user))


# ---------------------------------------------------------------------------
# HubCapture endpoints
# ---------------------------------------------------------------------------

class HubCaptureListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        kind = request.query_params.get("kind")
        status_filter = request.query_params.get("status", HubCaptureStatus.OPEN)
        group_slug = request.query_params.get("group")

        qs = HubCapture.objects.filter(owner=request.user, status=status_filter)

        if kind and kind in HubCaptureKind.values:
            qs = qs.filter(kind=kind)

        if group_slug:
            qs = qs.filter(group__slug=group_slug)
        else:
            qs = qs.filter(group__isnull=True)

        qs = qs.order_by("-created_at")[:50]

        return Response({
            "captures": [_serialize_capture(c) for c in qs],
        })

    def post(self, request):
        kind = request.data.get("kind")
        body = (request.data.get("body") or "").strip()
        group_slug = request.data.get("group_slug")
        remind_at = request.data.get("remind_at")
        visibility = request.data.get("visibility", HubCaptureVisibility.PRIVATE)

        if not kind or kind not in HubCaptureKind.values:
            return Response(
                {"error": f"kind must be one of: {', '.join(HubCaptureKind.values)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not body:
            return Response({"error": "body is required"}, status=status.HTTP_400_BAD_REQUEST)
        if visibility not in HubCaptureVisibility.values:
            visibility = HubCaptureVisibility.PRIVATE

        group = None
        if group_slug:
            from groups.models import Group
            try:
                group = Group.objects.get(slug=group_slug)
            except Group.DoesNotExist:
                return Response({"error": "group not found"}, status=status.HTTP_404_NOT_FOUND)

        # visibility only meaningful when group is set
        if not group:
            visibility = HubCaptureVisibility.PRIVATE

        capture = HubCapture.objects.create(
            owner=request.user,
            kind=kind,
            body=body,
            visibility=visibility,
            group=group,
            remind_at=remind_at or None,
        )
        return Response(_serialize_capture(capture), status=status.HTTP_201_CREATED)


class HubCaptureDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get_capture(self, request, capture_id):
        try:
            return HubCapture.objects.get(id=capture_id, owner=request.user)
        except HubCapture.DoesNotExist:
            return None

    def patch(self, request, capture_id):
        capture = self._get_capture(request, capture_id)
        if not capture:
            return Response(status=status.HTTP_404_NOT_FOUND)

        new_status = request.data.get("status")
        if new_status and new_status in HubCaptureStatus.values:
            capture.status = new_status
            if new_status == HubCaptureStatus.RESOLVED and not capture.resolved_at:
                capture.resolved_at = timezone.now()

        if "body" in request.data:
            capture.body = request.data["body"].strip()

        if "remind_at" in request.data:
            capture.remind_at = request.data["remind_at"] or None

        capture.save()
        return Response(_serialize_capture(capture))


class HubCaptureVoiceView(APIView):
    """
    POST /api/console/hub/captures/voice/
    Accept an audio file, persist it, queue Whisper transcription, and return
    immediately so the client can keep capture flow fast.
    """
    permission_classes = [permissions.IsAuthenticated]
    parser_classes_override = None  # uses default parsers including MultiPartParser

    def post(self, request):
        audio_file = request.FILES.get("audio")
        kind = request.data.get("kind", "note")
        group_slug = request.data.get("group_slug")

        if not audio_file:
            return Response({"error": "audio file required"}, status=status.HTTP_400_BAD_REQUEST)
        if kind not in HubCaptureKind.values:
            return Response({"error": f"kind must be one of: {', '.join(HubCaptureKind.values)}"}, status=status.HTTP_400_BAD_REQUEST)

        group = None
        if group_slug:
            from groups.models import Group
            try:
                group = Group.objects.get(slug=group_slug)
            except Group.DoesNotExist:
                return Response({"error": "group not found"}, status=status.HTTP_404_NOT_FOUND)

        base_name = audio_file.name or "voice-note.m4a"
        ext = (base_name.rsplit(".", 1)[-1].lower() if "." in base_name else "")
        unique = f"{uuid.uuid4()}.{ext}" if ext else str(uuid.uuid4())
        storage_key = f"console/audio/{request.user.id}/{unique}"

        audio_file.seek(0)
        saved_key = default_storage.save(storage_key, audio_file)
        stored = StoredFile.objects.create(
            file_path=saved_key,
            file_name=base_name,
            file_type=audio_file.content_type or "",
            file_size=audio_file.size or 0,
            uploaded_by=request.user,
            source=request.data.get("source") or "mobile-ops",
        )

        capture = HubCapture.objects.create(
            owner=request.user,
            kind=kind,
            body="Processing voice capture…",
            status=HubCaptureStatus.PROCESSING,
            group=group,
            audio_file=stored,
        )

        transcribe_hub_capture_task.delay(str(capture.id))

        return Response(
            {
                "capture": _serialize_capture(capture),
                "accepted": True,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class HubCapturePromoteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        capture_ids = request.data.get("capture_ids", [])
        target_kind = request.data.get("target_kind")  # "list" | "initiative"
        target_title = (request.data.get("target_title") or "").strip()

        if not capture_ids:
            return Response({"error": "capture_ids required"}, status=status.HTTP_400_BAD_REQUEST)
        if target_kind not in ("list", "initiative"):
            return Response({"error": "target_kind must be 'list' or 'initiative'"}, status=status.HTTP_400_BAD_REQUEST)
        if not target_title:
            return Response({"error": "target_title required"}, status=status.HTTP_400_BAD_REQUEST)

        captures = HubCapture.objects.filter(id__in=capture_ids, owner=request.user, status=HubCaptureStatus.OPEN)
        if not captures.exists():
            return Response({"error": "no matching open captures found"}, status=status.HTTP_404_NOT_FOUND)

        if target_kind == "list":
            from lists.models import List as MixtapeList
            from django.contrib.contenttypes.models import ContentType
            from django.contrib.auth import get_user_model
            body_lines = "\n".join(f"- {c.body}" for c in captures)
            user_ct = ContentType.objects.get_for_model(get_user_model())
            lst = MixtapeList.objects.create(
                sponsor_content_type=user_ct,
                sponsor_object_id=request.user.pk,
                author=request.user,
                submitted_by=request.user,
                title=target_title,
                body_text=body_lines,
            )
            from django.contrib.contenttypes.models import ContentType
            ct = ContentType.objects.get_for_model(MixtapeList)
            captures.update(
                status=HubCaptureStatus.PROMOTED,
                promoted_to_content_type=ct,
                promoted_to_object_id=lst.id,
            )
            return Response({"promoted_to": "list", "list_id": str(lst.id), "list_title": lst.title})

        return Response({"error": "initiative promotion not yet implemented"}, status=status.HTTP_501_NOT_IMPLEMENTED)


# ---------------------------------------------------------------------------
# WorkTable stream endpoint (WT-B1)
# ---------------------------------------------------------------------------

class WorkTableProseView(APIView):
    """
    POST /api/worktable/prose/
    WT-B6: Create a prose ApertureLogEntry for the member's Personal Initiative
    or a specified initiative. Thin wrapper over the existing ApertureLog entry API.

    Body: { "initiative_id": "uuid", "body": "string" }
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        initiative_id = request.data.get("initiative_id")
        body = (request.data.get("body") or "").strip()

        if not body:
            return Response({"error": "body is required"}, status=status.HTTP_400_BAD_REQUEST)

        from django.contrib.contenttypes.models import ContentType
        from initiatives.models import ApertureLog, ApertureLogEntry, ApertureLogEntryKind, Initiative

        if initiative_id:
            try:
                initiative = Initiative.objects.get(id=initiative_id)
            except Initiative.DoesNotExist:
                return Response({"error": "initiative not found"}, status=status.HTTP_404_NOT_FOUND)
        else:
            user_ct = ContentType.objects.get_for_model(request.user.__class__)
            initiative = (
                Initiative.objects
                .filter(
                    is_personal=True,
                    sponsor_content_type=user_ct,
                    sponsor_object_id=request.user.id,
                )
                .first()
            )
            if not initiative:
                display_name = (
                    request.user.get_full_name()
                    or request.user.username
                    or "Personal"
                )
                initiative = Initiative.objects.create(
                    title=f"{display_name}'s Personal Initiative",
                    sponsor_content_type=user_ct,
                    sponsor_object_id=request.user.id,
                    created_by=request.user,
                    is_personal=True,
                    rolling_summary={
                        "current_direction": "",
                        "key_decisions": [],
                        "open_questions": [],
                        "where_we_are_now": "",
                    },
                )

        aperture_log, _ = ApertureLog.objects.get_or_create(initiative=initiative)
        entry = ApertureLogEntry.objects.create(
            aperture_log=aperture_log,
            kind=ApertureLogEntryKind.PROSE,
            body=body,
            authored_by=request.user.username,
            created_by=request.user,
            is_system_generated=False,
        )

        return Response(
            {
                "id": str(entry.id),
                "entry_type": "prose",
                "kind": None,
                "body": entry.body,
                "created_at": entry.created_at.isoformat(),
            },
            status=status.HTTP_201_CREATED,
        )


class WorkTableStreamView(APIView):
    """
    GET /api/worktable/stream/

    Returns stream entries for the requesting user, scoped to personal, group,
    or initiative context. Cursor-paginated (before= ISO8601 timestamp).

    W1: entry_type=capture only (HubCaptures).
    W2 will add prose and ledger entries from ApertureLogEntry.
    W3 will wire initiative scope fully.
    """
    permission_classes = [permissions.IsAuthenticated]

    DEFAULT_LIMIT = 50
    MAX_LIMIT = 100

    def get(self, request):
        scope = request.query_params.get("scope", "personal")
        group_slug = request.query_params.get("group_slug")
        initiative_id = request.query_params.get("initiative_id")
        before = request.query_params.get("before")
        limit = min(int(request.query_params.get("limit", self.DEFAULT_LIMIT)), self.MAX_LIMIT)
        include_archived = request.query_params.get("include_archived", "false").lower() == "true"

        # ── Scope validation ─────────────────────────────────────────────────
        if scope == "group":
            if not group_slug:
                return Response({"error": "group_slug required for group scope"}, status=status.HTTP_400_BAD_REQUEST)
            from groups.models import Group, GroupMembership
            from django.contrib.contenttypes.models import ContentType
            from django.contrib.auth import get_user_model
            try:
                group = Group.objects.get(slug=group_slug)
            except Group.DoesNotExist:
                return Response({"error": "group not found"}, status=status.HTTP_404_NOT_FOUND)
            # Verify membership
            user_ct = ContentType.objects.get_for_model(get_user_model())
            if not GroupMembership.objects.filter(
                group=group,
                member_content_type=user_ct,
                member_object_id=request.user.pk,
                is_active=True,
            ).exists():
                return Response({"error": "not a member of this group"}, status=status.HTTP_403_FORBIDDEN)

        elif scope == "initiative":
            # WT-B8: return ApertureLogEntries interleaved with HubCaptures for the initiative
            if not initiative_id:
                return Response({"error": "initiative_id required for initiative scope"}, status=status.HTTP_400_BAD_REQUEST)

            from initiatives.models import ApertureLog, ApertureLogEntry
            try:
                aperture_log = ApertureLog.objects.get(initiative_id=initiative_id)
            except ApertureLog.DoesNotExist:
                return Response({"entries": [], "has_more": False, "cursor": None})

            log_entries_qs = aperture_log.entries.filter(deleted_at__isnull=True).order_by("created_at")
            if not include_archived:
                log_entries_qs = log_entries_qs.filter(archived_at__isnull=True)
            if before:
                try:
                    from django.utils.dateparse import parse_datetime
                    cursor_dt = parse_datetime(before)
                    if cursor_dt:
                        log_entries_qs = log_entries_qs.filter(created_at__lt=cursor_dt)
                except Exception:
                    pass

            log_entries = list(log_entries_qs[:limit + 1])
            has_more = len(log_entries) > limit
            if has_more:
                log_entries = log_entries[:limit]

            cursor = log_entries[-1].created_at.isoformat() if log_entries else None

            entries = [
                {
                    "id": str(e.id),
                    "entry_type": e.kind,
                    "kind": None,
                    "body": e.body,
                    "status": None,
                    "created_at": e.created_at.isoformat(),
                    "archived_at": e.archived_at.isoformat() if e.archived_at else None,
                    "metadata": {"ledger_event_type": e.ledger_event_type} if e.ledger_event_type else {},
                }
                for e in log_entries
            ]

            return Response({"entries": entries, "has_more": has_more, "cursor": cursor})

        # ── Build queryset ───────────────────────────────────────────────────
        qs = HubCapture.objects.filter(
            owner=request.user,
            deleted_at__isnull=True,
        ).order_by("created_at")
        if not include_archived:
            qs = qs.filter(archived_at__isnull=True)

        if scope == "personal":
            qs = qs.filter(group__isnull=True)
        elif scope == "group":
            # Show shared captures from all group members + requesting user's own private captures
            from django.db.models import Q
            qs = qs.filter(group__slug=group_slug).filter(
                Q(visibility=HubCaptureVisibility.SHARED) | Q(owner=request.user)
            )

        if before:
            try:
                from django.utils.dateparse import parse_datetime
                cursor_dt = parse_datetime(before)
                if cursor_dt:
                    qs = qs.filter(created_at__lt=cursor_dt)
            except Exception:
                pass

        # Fetch limit + 1 to determine has_more
        captures = list(qs[: limit + 1])

        # W2: merge ApertureLogEntries from personal initiative into personal scope stream
        log_entries = []
        if scope == "personal":
            from django.contrib.contenttypes.models import ContentType
            from django.contrib.auth import get_user_model
            from initiatives.models import ApertureLog, ApertureLogEntry, Initiative
            user_ct = ContentType.objects.get_for_model(get_user_model())
            personal_initiative = (
                Initiative.objects
                .filter(
                    is_personal=True,
                    sponsor_content_type=user_ct,
                    sponsor_object_id=request.user.pk,
                    deleted_at__isnull=True,
                )
                .first()
            )
            if personal_initiative:
                try:
                    aperture_log = ApertureLog.objects.get(initiative=personal_initiative)
                    log_qs = aperture_log.entries.filter(deleted_at__isnull=True).order_by("created_at")
                    if not include_archived:
                        log_qs = log_qs.filter(archived_at__isnull=True)
                    if before:
                        try:
                            from django.utils.dateparse import parse_datetime as _parse_dt
                            cursor_dt = _parse_dt(before)
                            if cursor_dt:
                                log_qs = log_qs.filter(created_at__lt=cursor_dt)
                        except Exception:
                            pass
                    log_entries = list(log_qs[: limit + 1])
                except ApertureLog.DoesNotExist:
                    pass

        # Merge captures and log entries, sort by created_at, paginate
        combined = [(c.created_at, "capture", c) for c in captures] + \
                   [(e.created_at, "log", e) for e in log_entries]
        combined.sort(key=lambda x: x[0])

        has_more = len(combined) > limit
        if has_more:
            combined = combined[:limit]

        cursor = combined[-1][0].isoformat() if combined else None

        entries = []
        for _ts, kind, item in combined:
            if kind == "capture":
                entries.append({
                    "id": str(item.id),
                    "entry_type": "capture",
                    "kind": item.kind,
                    "body": item.body,
                    "status": item.status,
                    "visibility": item.visibility,
                    "created_at": item.created_at.isoformat(),
                    "archived_at": item.archived_at.isoformat() if item.archived_at else None,
                    "metadata": {},
                })
            else:
                entries.append({
                    "id": str(item.id),
                    "entry_type": item.kind,
                    "kind": None,
                    "body": item.body,
                    "status": None,
                    "created_at": item.created_at.isoformat(),
                    "archived_at": item.archived_at.isoformat() if item.archived_at else None,
                    "metadata": {"ledger_event_type": item.ledger_event_type} if item.ledger_event_type else {},
                })

        return Response({"entries": entries, "has_more": has_more, "cursor": cursor})


# ---------------------------------------------------------------------------
# WorkTable entry actions — archive and soft-delete
# ---------------------------------------------------------------------------

def _get_stream_entry_for_user(entry_id: str, user):
    """
    Resolves a stream entry UUID to either a HubCapture or ApertureLogEntry and
    verifies the requesting user has write access to it.

    Returns (obj, "capture"|"log_entry").
    Raises Http404 if not found, PermissionDenied if not owner/author.
    """
    from django.core.exceptions import PermissionDenied
    from django.http import Http404
    from initiatives.models import ApertureLogEntry

    # Try HubCapture first
    try:
        capture = HubCapture.objects.get(id=entry_id, deleted_at__isnull=True)
        if capture.owner_id != user.pk:
            raise PermissionDenied
        return capture, "capture"
    except HubCapture.DoesNotExist:
        pass

    # Try ApertureLogEntry
    try:
        entry = ApertureLogEntry.objects.get(id=entry_id, deleted_at__isnull=True)
        if not entry.is_system_generated and entry.created_by_id != user.pk:
            raise PermissionDenied
        return entry, "log_entry"
    except ApertureLogEntry.DoesNotExist:
        raise Http404


class WorkTableEntryArchiveView(APIView):
    """
    POST /api/worktable/entries/{entry_id}/archive/

    Sets archived_at on a HubCapture or ApertureLogEntry owned by the requesting
    user. Archived entries are excluded from the default stream view but visible
    when include_archived=true is passed to the stream endpoint.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, entry_id):
        from django.core.exceptions import PermissionDenied
        from django.http import Http404

        try:
            obj, _ = _get_stream_entry_for_user(entry_id, request.user)
        except Http404:
            return Response({"error": "entry not found"}, status=status.HTTP_404_NOT_FOUND)
        except PermissionDenied:
            return Response({"error": "forbidden"}, status=status.HTTP_403_FORBIDDEN)

        if obj.archived_at is None:
            obj.archived_at = timezone.now()
            obj.save(update_fields=["archived_at", "updated_at"])

        return Response({"archived_at": obj.archived_at.isoformat()})


class WorkTableEntryDeleteView(APIView):
    """
    DELETE /api/worktable/entries/{entry_id}/

    Soft-deletes a HubCapture or user-authored ApertureLogEntry by setting
    deleted_at. System-generated ledger entries cannot be deleted.
    """
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, entry_id):
        from django.core.exceptions import PermissionDenied
        from django.http import Http404
        from initiatives.models import ApertureLogEntry

        try:
            obj, entry_type = _get_stream_entry_for_user(entry_id, request.user)
        except Http404:
            return Response({"error": "entry not found"}, status=status.HTTP_404_NOT_FOUND)
        except PermissionDenied:
            return Response({"error": "forbidden"}, status=status.HTTP_403_FORBIDDEN)

        if entry_type == "log_entry" and isinstance(obj, ApertureLogEntry) and obj.is_system_generated:
            return Response({"error": "system-generated entries cannot be deleted"}, status=status.HTTP_403_FORBIDDEN)

        if obj.deleted_at is None:
            obj.deleted_at = timezone.now()
            obj.save(update_fields=["deleted_at", "updated_at"])

        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_capture(c: HubCapture) -> dict:
    return {
        "id": str(c.id),
        "kind": c.kind,
        "body": c.body,
        "status": c.status,
        "transcript_error": c.transcript_error,
        "visibility": c.visibility,
        "group_id": str(c.group_id) if c.group_id else None,
        "remind_at": c.remind_at.isoformat() if c.remind_at else None,
        "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
        "created_at": c.created_at.isoformat(),
    }
