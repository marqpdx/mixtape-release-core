from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from console import services
from console.models import HubCapture, HubCaptureKind, HubCaptureStatus


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

        if not kind or kind not in HubCaptureKind.values:
            return Response(
                {"error": f"kind must be one of: {', '.join(HubCaptureKind.values)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not body:
            return Response({"error": "body is required"}, status=status.HTTP_400_BAD_REQUEST)

        group = None
        if group_slug:
            from groups.models import Group
            try:
                group = Group.objects.get(slug=group_slug)
            except Group.DoesNotExist:
                return Response({"error": "group not found"}, status=status.HTTP_404_NOT_FOUND)

        capture = HubCapture.objects.create(
            owner=request.user,
            kind=kind,
            body=body,
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
            body_lines = "\n".join(f"- {c.body}" for c in captures)
            lst = MixtapeList.objects.create(
                owner=request.user,
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
# Helpers
# ---------------------------------------------------------------------------

def _serialize_capture(c: HubCapture) -> dict:
    return {
        "id": str(c.id),
        "kind": c.kind,
        "body": c.body,
        "status": c.status,
        "group_id": str(c.group_id) if c.group_id else None,
        "remind_at": c.remind_at.isoformat() if c.remind_at else None,
        "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
        "created_at": c.created_at.isoformat(),
    }
