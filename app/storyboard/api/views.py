# storyboard/api/views.py
#
# Phase 5 policy: author-only (build-handoff §2a). A user may see, create,
# reorder, or edit a Storyboard and its StoryboardItems iff
# storyboard.created_by == request.user (or is_staff) -- same shape of
# check as Folio's, applied at the queryset/get_object_or_404 level.

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from folio.models import Folio
from storyboard.grammars import get_grammar
from storyboard.models import Entity, Participation, Storyboard, StoryboardFolio, StoryboardItem, StoryboardItemLink, SurfaceState
from storyboard.services import add_note_link, add_participation, create_item, create_scene, reorder_siblings, reparent_item
from folio.models import FolioNote

from .serializers import (
    StoryboardCreateSerializer,
    StoryboardFolioUpdateSerializer,
    StoryboardItemCreateSerializer,
    StoryboardItemSerializer,
    StoryboardItemUpdateSerializer,
    StoryboardReorderSerializer,
    StoryboardSerializer,
    SurfaceStatePatchSerializer,
    ParticipationCreateSerializer,
    NoteLinkCreateSerializer,
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

        folio_ids = serializer.validated_data.get("folio_ids", [])
        folios = list(Folio.objects.filter(pk__in=folio_ids, created_by=request.user))
        if len(folios) != len(set(folio_ids)):
            return Response({"folio_ids": ["All Folios must be owned by you."]}, status=status.HTTP_400_BAD_REQUEST)

        # Phase 5 policy: personal sponsor only -- Storyboard.sponsor is
        # persisted at creation and never re-derived later (build-handoff
        # §2a). Group-sponsored Storyboards are a real future need, not
        # required by Phase 5's acceptance criteria.
        user_ct = ContentType.objects.get_for_model(User)
        with transaction.atomic():
            storyboard = Storyboard.objects.create(
                kind="writing",
                grammar=grammar_key,
                title=serializer.validated_data.get("title", ""),
                created_by=request.user,
                sponsor_content_type=user_ct,
                sponsor_object_id=request.user.id,
            )
            StoryboardFolio.objects.bulk_create([
                StoryboardFolio(storyboard=storyboard, folio=folio) for folio in folios
            ])
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
                "surface_states": [
                    {"item_id": str(state.item_id), "x": state.x, "y": state.y,
                     "size": state.size, "expanded": state.expanded}
                    for state in SurfaceState.objects.filter(item__storyboard=storyboard, user=request.user)
                ],
                "participations": [
                    {"id": part.id, "item_id": str(part.item_id), "entity_id": str(part.entity_id),
                     "kind": part.kind, "name": part.entity.name, "entity_kind": part.entity.kind}
                    for part in Participation.objects.filter(item__storyboard=storyboard).select_related("entity")
                ],
                "links": [
                    {"id": link.id, "item_id": str(link.item_id), "kind": link.kind,
                     "target_id": str(link.target_object_id)}
                    for link in StoryboardItemLink.objects.filter(item__storyboard=storyboard)
                ],
            }
        )

    def patch(self, request, storyboard_id):
        storyboard = _get_owned_storyboard(request.user, storyboard_id)
        serializer = StoryboardFolioUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        folio_ids = serializer.validated_data["folio_ids"]
        folios = list(Folio.objects.filter(pk__in=folio_ids, created_by=request.user))
        if len(folios) != len(set(folio_ids)):
            return Response({"folio_ids": ["All Folios must be owned by you."]}, status=status.HTTP_400_BAD_REQUEST)
        storyboard.folios.set(folios)
        return Response(StoryboardSerializer(storyboard).data)


class StoryboardNoteListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, storyboard_id):
        from folio.api.serializers import FolioNoteSerializer

        storyboard = _get_owned_storyboard(request.user, storyboard_id)
        notes = FolioNote.objects.filter(folio__in=storyboard.folios.all(), folio__created_by=request.user).order_by("-created_at")[:200]
        return Response(FolioNoteSerializer(notes, many=True).data)


class StoryboardEntityListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, storyboard_id):
        storyboard = _get_owned_storyboard(request.user, storyboard_id)
        entities = Entity.objects.filter(
            sponsor_content_type=storyboard.sponsor_content_type,
            sponsor_object_id=storyboard.sponsor_object_id,
        ).order_by("name")
        return Response([{"id": str(entity.id), "kind": entity.kind, "name": entity.name,
                          "aliases": entity.aliases} for entity in entities])


class StoryboardParticipationView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, storyboard_id, item_id):
        storyboard = _get_owned_storyboard(request.user, storyboard_id)
        item = get_object_or_404(StoryboardItem, pk=item_id, storyboard=storyboard)
        serializer = ParticipationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        entity = None
        if data.get("entity_id"):
            entity = get_object_or_404(
                Entity, pk=data["entity_id"],
                sponsor_content_type=storyboard.sponsor_content_type,
                sponsor_object_id=storyboard.sponsor_object_id,
            )
        name = data.get("name", "")
        note = None
        mention = None
        if data.get("note_id") is not None:
            note = get_object_or_404(FolioNote, pk=data["note_id"], folio__in=storyboard.folios.all(), folio__created_by=request.user)
            index = data.get("mention_index")
            if index is None or index >= len(note.mentions):
                return Response({"detail": "Choose a valid mention candidate."}, status=status.HTTP_400_BAD_REQUEST)
            mention = note.mentions[index]
            name = name or mention.get("surface", "")
        try:
            participation = add_participation(item=item, kind=data["kind"], user=request.user, entity=entity, name=name)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if note is not None and mention is not None:
            mention["confirmed_entity_id"] = str(participation.entity_id)
            mention["confirmed_kind"] = data["kind"]
            note.save(update_fields=["mentions", "updated_at"])
        return Response({"id": participation.id, "item_id": str(item.id), "entity_id": str(participation.entity_id),
                         "kind": participation.kind, "name": participation.entity.name}, status=status.HTTP_201_CREATED)


class StoryboardParticipationDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, storyboard_id, item_id, participation_id):
        storyboard = _get_owned_storyboard(request.user, storyboard_id)
        participation = get_object_or_404(Participation, pk=participation_id, item_id=item_id, item__storyboard=storyboard)
        participation.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class StoryboardItemLinkView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, storyboard_id, item_id):
        storyboard = _get_owned_storyboard(request.user, storyboard_id)
        item = get_object_or_404(StoryboardItem, pk=item_id, storyboard=storyboard)
        serializer = NoteLinkCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = get_object_or_404(FolioNote, pk=serializer.validated_data["note_id"], folio__created_by=request.user)
        try:
            link = add_note_link(item=item, note=note, user=request.user)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"id": link.id, "item_id": str(item.id), "kind": "note", "target_id": str(note.id)}, status=status.HTTP_201_CREATED)


class StoryboardItemLinkDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, storyboard_id, item_id, link_id):
        storyboard = _get_owned_storyboard(request.user, storyboard_id)
        link = get_object_or_404(StoryboardItemLink, pk=link_id, item_id=item_id, item__storyboard=storyboard)
        link.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class StoryboardSurfaceStateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, storyboard_id, item_id):
        storyboard = _get_owned_storyboard(request.user, storyboard_id)
        item = get_object_or_404(StoryboardItem, pk=item_id, storyboard=storyboard)
        serializer = SurfaceStatePatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        state, _ = SurfaceState.objects.get_or_create(item=item, user=request.user)
        for field, value in serializer.validated_data.items():
            setattr(state, field, value)
        state.save()
        return Response({"item_id": str(item.id), "x": state.x, "y": state.y,
                         "size": state.size, "expanded": state.expanded})


class StoryboardResetLayoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, storyboard_id):
        storyboard = _get_owned_storyboard(request.user, storyboard_id)
        SurfaceState.objects.filter(item__storyboard=storyboard, user=request.user).update(x=None, y=None)
        return Response({"reset": True})


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
