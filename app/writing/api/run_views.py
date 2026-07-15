# writing/api/run_views.py
# ADR-0054: Writing Assembly — Run Board and Publish Cascade

from django.db import transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from writing.models import WritingPiece, WritingRun, WritingRunMembership


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

class RunMemberSerializer(serializers.ModelSerializer):
    piece_id = serializers.UUIDField(source="piece.id", read_only=True)
    piece_title = serializers.CharField(source="piece.title", read_only=True)
    piece_status = serializers.CharField(source="piece.status", read_only=True)
    spellcheck_clean = serializers.BooleanField(source="piece.spellcheck_clean", read_only=True)
    signed_off = serializers.BooleanField(source="piece.signed_off", read_only=True)
    word_count = serializers.SerializerMethodField()

    class Meta:
        model = WritingRunMembership
        fields = [
            "id", "order_index", "added_at",
            "piece_id", "piece_title", "piece_status",
            "spellcheck_clean", "signed_off", "word_count",
        ]

    def get_word_count(self, obj):
        from utils.writing.writing_utils import count_words_in_prosemirror
        try:
            return count_words_in_prosemirror(obj.piece.body_json) if obj.piece.body_json else 0
        except Exception:
            return 0


class WritingRunSerializer(serializers.ModelSerializer):
    memberships = RunMemberSerializer(many=True, read_only=True)
    member_count = serializers.SerializerMethodField()
    is_publishable = serializers.SerializerMethodField()

    class Meta:
        model = WritingRun
        fields = [
            "id", "title", "slug", "status", "published_at",
            "created_at", "updated_at",
            "memberships", "member_count", "is_publishable",
        ]
        read_only_fields = ["id", "slug", "status", "published_at", "created_at", "updated_at"]

    def get_member_count(self, obj):
        return obj.memberships.count()

    def get_is_publishable(self, obj):
        if obj.status == "published":
            return False
        memberships = obj.memberships.select_related("piece")
        if not memberships.exists():
            return False
        return all(m.piece.spellcheck_clean and m.piece.signed_off for m in memberships)


class WritingRunListSerializer(serializers.ModelSerializer):
    member_count = serializers.SerializerMethodField()
    is_publishable = serializers.SerializerMethodField()

    class Meta:
        model = WritingRun
        fields = [
            "id", "title", "slug", "status", "published_at",
            "created_at", "updated_at", "member_count", "is_publishable",
        ]
        read_only_fields = fields

    def get_member_count(self, obj):
        return obj.memberships.count()

    def get_is_publishable(self, obj):
        if obj.status == "published":
            return False
        memberships = obj.memberships.select_related("piece")
        if not memberships.exists():
            return False
        return all(m.piece.spellcheck_clean and m.piece.signed_off for m in memberships)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_run_for_user(run_id, user):
    """Fetch a WritingRun owned by the given user (member sponsor)."""
    from django.contrib.contenttypes.models import ContentType
    user_ct = ContentType.objects.get_for_model(user)
    return get_object_or_404(
        WritingRun,
        id=run_id,
        sponsor_content_type=user_ct,
        sponsor_object_id=str(user.pk),
    )


def _get_sponsor_ct_and_id(user):
    from django.contrib.contenttypes.models import ContentType
    ct = ContentType.objects.get_for_model(user)
    return ct, str(user.pk)


# ---------------------------------------------------------------------------
# Views — Runs
# ---------------------------------------------------------------------------

class WritingRunListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        ct, obj_id = _get_sponsor_ct_and_id(request.user)
        runs = WritingRun.objects.filter(
            sponsor_content_type=ct,
            sponsor_object_id=obj_id,
        ).order_by("-updated_at")
        return Response(WritingRunListSerializer(runs, many=True).data)

    def post(self, request):
        title = (request.data.get("title") or "").strip()
        if not title:
            return Response({"title": "Title is required."}, status=status.HTTP_400_BAD_REQUEST)
        ct, obj_id = _get_sponsor_ct_and_id(request.user)
        run = WritingRun.objects.create(
            title=title,
            sponsor_content_type=ct,
            sponsor_object_id=obj_id,
        )
        return Response(WritingRunSerializer(run).data, status=status.HTTP_201_CREATED)


class WritingRunDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, run_id):
        run = _get_run_for_user(run_id, request.user)
        return Response(WritingRunSerializer(run).data)

    def patch(self, request, run_id):
        run = _get_run_for_user(run_id, request.user)
        title = request.data.get("title")
        if title is not None:
            run.title = title.strip()
        run.save()
        return Response(WritingRunSerializer(run).data)

    def delete(self, request, run_id):
        run = _get_run_for_user(run_id, request.user)
        run.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WritingRunPublishView(APIView):
    """
    Gate-up check + cascade-down publish.
    All member Docs must be Green (spellcheck_clean + signed_off) before publish.
    Publishing atomically sets all member Docs to published status.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, run_id):
        run = _get_run_for_user(run_id, request.user)

        if run.status == "published":
            return Response({"detail": "Run is already published."}, status=status.HTTP_400_BAD_REQUEST)

        memberships = list(run.memberships.select_related("piece").order_by("order_index"))
        if not memberships:
            return Response({"detail": "Cannot publish an empty Run."}, status=status.HTTP_400_BAD_REQUEST)

        not_ready = [m.piece.title or str(m.piece.id) for m in memberships
                     if not (m.piece.spellcheck_clean and m.piece.signed_off)]
        if not_ready:
            return Response(
                {"detail": "All Docs must be spellcheck-clean and signed off before publishing.",
                 "not_ready": not_ready},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            now = timezone.now()
            pieces = [m.piece for m in memberships]
            for piece in pieces:
                if piece.status != "published":
                    piece.status = "published"
                    piece.published_at = now
                    piece.save(update_fields=["status", "published_at", "updated_at"])
            run.status = "published"
            run.published_at = now
            run.save(update_fields=["status", "published_at", "updated_at"])

        return Response(WritingRunSerializer(run).data)


# ---------------------------------------------------------------------------
# Views — Run Members
# ---------------------------------------------------------------------------

class WritingRunMembersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, run_id):
        run = _get_run_for_user(run_id, request.user)
        memberships = run.memberships.select_related("piece").order_by("order_index")
        return Response(RunMemberSerializer(memberships, many=True).data)

    def post(self, request, run_id):
        run = _get_run_for_user(run_id, request.user)
        piece_id = request.data.get("piece_id")
        if not piece_id:
            return Response({"piece_id": "Required."}, status=status.HTTP_400_BAD_REQUEST)

        piece = get_object_or_404(WritingPiece, id=piece_id)

        # Verify the piece belongs to the same sponsor
        from django.contrib.contenttypes.models import ContentType
        user_ct = ContentType.objects.get_for_model(request.user)
        if piece.sponsor_content_type != user_ct or str(piece.sponsor_object_id) != str(request.user.pk):
            return Response({"detail": "Piece does not belong to your writing."}, status=status.HTTP_403_FORBIDDEN)

        if WritingRunMembership.objects.filter(run=run, piece=piece).exists():
            return Response({"detail": "Piece is already in this Run."}, status=status.HTTP_400_BAD_REQUEST)

        max_index = run.memberships.aggregate(m=Max("order_index"))["m"]
        order_index = (max_index or -1) + 1

        membership = WritingRunMembership.objects.create(run=run, piece=piece, order_index=order_index)

        # Adding a piece reverts a published Run to draft
        if run.status == "published":
            run.status = "draft"
            run.published_at = None
            run.save(update_fields=["status", "published_at", "updated_at"])

        return Response(RunMemberSerializer(membership).data, status=status.HTTP_201_CREATED)


class WritingRunMemberDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, run_id, piece_id):
        run = _get_run_for_user(run_id, request.user)
        membership = get_object_or_404(WritingRunMembership, run=run, piece_id=piece_id)
        membership.delete()

        # Removing a piece reverts a published Run to draft
        if run.status == "published":
            run.status = "draft"
            run.published_at = None
            run.save(update_fields=["status", "published_at", "updated_at"])

        return Response(status=status.HTTP_204_NO_CONTENT)


class WritingRunMembersReorderView(APIView):
    """
    PATCH with {"piece_ids": [...]} in new order.
    Reordering a published Run reverts it to draft (D6).
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, run_id):
        run = _get_run_for_user(run_id, request.user)
        piece_ids = request.data.get("piece_ids")
        if not isinstance(piece_ids, list):
            return Response({"piece_ids": "Must be a list of piece UUIDs."}, status=status.HTTP_400_BAD_REQUEST)

        memberships = {str(m.piece_id): m for m in run.memberships.all()}

        if set(piece_ids) != set(memberships.keys()):
            return Response(
                {"detail": "piece_ids must contain exactly the current member piece IDs."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        was_published = run.status == "published"

        with transaction.atomic():
            for idx, pid in enumerate(piece_ids):
                m = memberships[str(pid)]
                m.order_index = idx
                m.save(update_fields=["order_index"])

            if was_published:
                run.status = "draft"
                run.published_at = None
                run.save(update_fields=["status", "published_at", "updated_at"])

        run.refresh_from_db()
        return Response(WritingRunSerializer(run).data)


# ---------------------------------------------------------------------------
# Views — Piece sign-off toggle (D10)
# ---------------------------------------------------------------------------

class WritingPieceSignOffView(APIView):
    """POST to set signed_off=True on a piece. Cleared automatically on next body edit."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        piece = get_object_or_404(WritingPiece, id=pk)
        if piece.author != request.user:
            return Response(status=status.HTTP_403_FORBIDDEN)
        piece.signed_off = True
        piece.save(update_fields=["signed_off", "updated_at"])
        return Response({"signed_off": True, "piece_id": str(piece.id)})
