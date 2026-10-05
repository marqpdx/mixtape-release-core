# storyboard/api/views.py
#
# Phase 5 policy: author-only (build-handoff §2a). A user may see, create,
# reorder, or edit a Storyboard and its StoryboardItems iff
# storyboard.created_by == request.user (or is_staff) -- same shape of
# check as Folio's, applied at the queryset/get_object_or_404 level.

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from folio.models import Folio
from storyboard.grammars import get_grammar
from storyboard.models import Storyboard, StoryboardItem
from storyboard.services import create_item, create_scene, reorder_siblings, reparent_item

from .serializers import (
    StoryboardCreateSerializer,
    StoryboardItemCreateSerializer,
    StoryboardItemSerializer,
    StoryboardItemUpdateSerializer,
    StoryboardReorderSerializer,
    StoryboardSerializer,
)

User = get_user_model()


def _get_owned_storyboard(user, storyboard_id):
    storyboard = get_object_or_404(Storyboard, pk=storyboard_id)
    if storyboard.created_by_id != user.id and not getattr(user, "is_staff", False):
        # 404, not 403 -- don't reveal that a Storyboard belonging to
        # someone else exists at this id (same posture as Folio's views).
        raise Http404
    return storyboard


class StoryboardListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        storyboards = Storyboard.objects.filter(created_by=request.user)
        return Response(StoryboardSerializer(storyboards, many=True).data)

    def post(self, request):
        serializer = StoryboardCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        grammar_key = serializer.validated_data["grammar"]
        try:
            get_grammar(grammar_key)
        except ValueError as exc:
            return Response({"grammar": [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)

        folio = None
        folio_id = serializer.validated_data.get("folio_id")
        if folio_id:
            folio = get_object_or_404(Folio, pk=folio_id, created_by=request.user)

        # Phase 5 policy: personal sponsor only -- Storyboard.sponsor is
        # persisted at creation and never re-derived later (build-handoff
        # §2a). Group-sponsored Storyboards are a real future need, not
        # required by Phase 5's acceptance criteria.
        user_ct = ContentType.objects.get_for_model(User)
        storyboard = Storyboard.objects.create(
            kind="writing",
            grammar=grammar_key,
            title=serializer.validated_data.get("title", ""),
            folio=folio,
            created_by=request.user,
            sponsor_content_type=user_ct,
            sponsor_object_id=request.user.id,
        )
        return Response(StoryboardSerializer(storyboard).data, status=status.HTTP_201_CREATED)


class StoryboardDetailView(APIView):
    """GET returns the Storyboard plus its full flat item list -- the
    client builds the tree from parent_id (Linear View)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, storyboard_id):
        storyboard = _get_owned_storyboard(request.user, storyboard_id)
        items = StoryboardItem.objects.filter(storyboard=storyboard).select_related(
            "reference_content_type"
        )
        return Response(
            {
                "storyboard": StoryboardSerializer(storyboard).data,
                "items": StoryboardItemSerializer(items, many=True).data,
            }
        )


class StoryboardItemListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, storyboard_id):
        storyboard = _get_owned_storyboard(request.user, storyboard_id)
        serializer = StoryboardItemCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        level = serializer.validated_data["level"]
        title = serializer.validated_data.get("title", "")
        parent = None
        parent_id = serializer.validated_data.get("parent_id")
        if parent_id:
            parent = get_object_or_404(StoryboardItem, pk=parent_id, storyboard=storyboard)

        try:
            # Validate the grammar key up front so an unknown grammar
            # produces a clean 400 instead of an AttributeError below.
            get_grammar(storyboard.grammar)
            # create_scene is specifically "scene" + its WritingPiece, per
            # fiction_v1; a purely structural level (part/chapter) just
            # gets a bare item. Generalize this dispatch if a second
            # grammar introduces another WritingPiece-referencing level.
            if level == "scene":
                item = create_scene(storyboard=storyboard, parent=parent, title=title)
            else:
                item = create_item(storyboard=storyboard, level=level, parent=parent, title=title)
        except (ValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(StoryboardItemSerializer(item).data, status=status.HTTP_201_CREATED)


class StoryboardItemDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, storyboard_id, item_id):
        storyboard = _get_owned_storyboard(request.user, storyboard_id)
        item = get_object_or_404(StoryboardItem, pk=item_id, storyboard=storyboard)

        serializer = StoryboardItemUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data

        update_fields = []
        if "title" in data:
            item.title = data["title"]
            update_fields.append("title")
        if "head" in data:
            item.head = data["head"]
            update_fields.append("head")
        if update_fields:
            item.save(update_fields=update_fields + ["updated_at"])

        # "parent_id" being present (even if null, meaning "move to root")
        # signals a move -- distinct from the field simply being absent.
        if "parent_id" in request.data:
            new_parent = None
            if data.get("parent_id"):
                new_parent = get_object_or_404(
                    StoryboardItem, pk=data["parent_id"], storyboard=storyboard
                )
            try:
                item = reparent_item(
                    item=item, new_parent=new_parent, new_rank=data.get("rank")
                )
            except ValidationError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        item.refresh_from_db()
        return Response(StoryboardItemSerializer(item).data)


class StoryboardReorderView(APIView):
    """POST /storyboards/<id>/items/reorder -- deliberately reorder the
    story (build-handoff §5, acceptance item 7)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, storyboard_id):
        storyboard = _get_owned_storyboard(request.user, storyboard_id)
        serializer = StoryboardReorderSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        parent = None
        parent_id = serializer.validated_data.get("parent_id")
        if parent_id:
            parent = get_object_or_404(StoryboardItem, pk=parent_id, storyboard=storyboard)

        try:
            reorder_siblings(
                storyboard=storyboard,
                parent=parent,
                ordered_item_ids=serializer.validated_data["ordered_item_ids"],
            )
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        items = StoryboardItem.objects.filter(storyboard=storyboard, parent=parent)
        return Response(StoryboardItemSerializer(items, many=True).data)
