from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from groups.services.permissions import PermissionService
from lists.api.serializers import (
    ListCreateSerializer,
    ListItemAnnotationSerializer,
    ListItemPromoteSerializer,
    ListSerializer,
    ListUpdateSerializer,
)
from lists.models import List, ListItemAnnotation
from lists.parser import (
    parse_list_text,
    serialize_list_items,
    toggle_item_completion,
    reorder_items,
)


class ListRootView(APIView):
    """
    GET /api/lists/ - List recent lists for the current user (or specified sponsor)
    POST /api/lists/ - Create a new list
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        raw_ct = request.query_params.get("sponsor_type") or request.query_params.get(
            "sponsor_content_type"
        )
        sponsor_object_id = request.query_params.get("sponsor_object_id")

        # Default to current user's lists
        if not raw_ct or not sponsor_object_id:
            sponsor_content_type = ContentType.objects.get_for_model(user.__class__)
            sponsor_object_id = user.id
        else:
            from utils.shared.contenttypes import resolve_content_type

            sponsor_content_type = resolve_content_type(raw_ct)

            # Permission check for non-self sponsors
            if not (user.is_staff or user.is_superuser):
                if sponsor_content_type.model == "group":
                    from groups.models import Group

                    sponsor = get_object_or_404(Group, id=sponsor_object_id, is_active=True)
                    allowed = PermissionService.can_user_perform_action(
                        user,
                        "can_view_list",
                        group_slug=sponsor.slug,
                    )
                    if not allowed:
                        return Response(
                            {"detail": "You don't have permission to view lists for this group."},
                            status=status.HTTP_403_FORBIDDEN,
                        )
                else:
                    user_ct = ContentType.objects.get_for_model(user.__class__)
                    if sponsor_content_type != user_ct or str(sponsor_object_id) != str(user.id):
                        return Response(
                            {"detail": "You can only view your own lists."},
                            status=status.HTTP_403_FORBIDDEN,
                        )

        lists = List.objects.filter(
            sponsor_content_type=sponsor_content_type,
            sponsor_object_id=sponsor_object_id,
            deleted_at__isnull=True,
        ).order_by("-updated_at")[:50]

        return Response(ListSerializer(lists, many=True).data)

    def post(self, request):
        serializer = ListCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        sponsor_content_type = serializer.validated_data.get("sponsor_content_type")
        sponsor_object_id = serializer.validated_data.get("sponsor_object_id")

        # Default sponsor to current user
        if not sponsor_content_type:
            sponsor_content_type = ContentType.objects.get_for_model(user.__class__)
            sponsor_object_id = user.id

        # Permission check
        if not (user.is_staff or user.is_superuser):
            if sponsor_content_type.model == "group":
                from groups.models import Group

                sponsor = get_object_or_404(Group, id=sponsor_object_id, is_active=True)
                allowed = PermissionService.can_user_perform_action(
                    user,
                    "can_edit_list",
                    group_slug=sponsor.slug,
                )
                if not allowed:
                    return Response(
                        {"detail": "You don't have permission to create a list for this group."},
                        status=status.HTTP_403_FORBIDDEN,
                    )
            else:
                user_ct = ContentType.objects.get_for_model(user.__class__)
                if sponsor_content_type != user_ct or str(sponsor_object_id) != str(user.id):
                    return Response(
                        {"detail": "You can only create lists for yourself."},
                        status=status.HTTP_403_FORBIDDEN,
                    )

        lst = List.objects.create(
            title=serializer.validated_data["title"],
            body_text=serializer.validated_data.get("body_text", ""),
            submitted_by=user,
            author=user,
            sponsor_content_type=sponsor_content_type,
            sponsor_object_id=sponsor_object_id,
        )

        return Response(ListSerializer(lst).data, status=status.HTTP_201_CREATED)


class ListDetailView(APIView):
    """
    GET /api/lists/<id>/
    PATCH /api/lists/<id>/
    DELETE /api/lists/<id>/
    """

    permission_classes = [permissions.IsAuthenticated]

    def _get_list_and_check_permission(self, request, list_id, action="view"):
        lst = get_object_or_404(List, id=list_id, deleted_at__isnull=True)
        user = request.user

        if user.is_staff or user.is_superuser:
            return lst

        sponsor_ct = lst.sponsor_content_type
        if sponsor_ct.model == "group":
            from groups.models import Group

            sponsor = get_object_or_404(Group, id=lst.sponsor_object_id, is_active=True)
            permission_name = f"can_{action}_list"
            allowed = PermissionService.can_user_perform_action(
                user,
                permission_name,
                group_slug=sponsor.slug,
            )
            if not allowed:
                return None
        else:
            # User-sponsored: must be the sponsor
            if str(lst.sponsor_object_id) != str(user.id):
                return None

        return lst

    def get(self, request, list_id):
        lst = self._get_list_and_check_permission(request, list_id, action="view")
        if lst is None:
            return Response(
                {"detail": "You don't have permission to view this list."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(ListSerializer(lst).data)

    def patch(self, request, list_id):
        lst = self._get_list_and_check_permission(request, list_id, action="edit")
        if lst is None:
            return Response(
                {"detail": "You don't have permission to edit this list."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = ListUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if "title" in serializer.validated_data:
            lst.title = serializer.validated_data["title"]
        if "body_text" in serializer.validated_data:
            lst.body_text = serializer.validated_data["body_text"]
        if "summary" in serializer.validated_data:
            lst.summary = serializer.validated_data["summary"]

        lst.save()
        return Response(ListSerializer(lst).data)

    def delete(self, request, list_id):
        lst = self._get_list_and_check_permission(request, list_id, action="edit")
        if lst is None:
            return Response(
                {"detail": "You don't have permission to delete this list."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Soft delete
        from django.utils import timezone

        lst.deleted_at = timezone.now()
        lst.save(update_fields=["deleted_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ListSearchView(APIView):
    """
    GET /api/lists/search/?q=<query>
    Search lists by title or slug for the current user.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        query = request.query_params.get("q", "").strip()

        if not query:
            return Response(
                {"detail": "Query parameter 'q' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Default to searching user's own lists
        user_ct = ContentType.objects.get_for_model(user.__class__)

        # Search by title or slug (prefix match preferred)
        lists = (
            List.objects.filter(
                sponsor_content_type=user_ct,
                sponsor_object_id=user.id,
                deleted_at__isnull=True,
            )
            .filter(Q(title__icontains=query) | Q(slug__icontains=query))
            .order_by("-updated_at")[:20]
        )

        return Response(ListSerializer(lists, many=True).data)


class ListBySlugView(APIView):
    """
    GET /api/lists/by-slug/<slug>/
    Get a list by slug for the current user.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        user = request.user
        user_ct = ContentType.objects.get_for_model(user.__class__)

        lst = List.objects.filter(
            sponsor_content_type=user_ct,
            sponsor_object_id=user.id,
            slug=slug,
            deleted_at__isnull=True,
        ).first()

        if not lst:
            return Response(
                {"detail": "List not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(ListSerializer(lst).data)


class ListItemToggleView(APIView):
    """
    POST /api/lists/<id>/items/<index>/toggle
    Toggle an item's completion status (- ↔ x).
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, list_id, item_index):
        lst = get_object_or_404(List, id=list_id, deleted_at__isnull=True)
        user = request.user

        # Permission check
        if not (user.is_staff or user.is_superuser):
            sponsor_ct = lst.sponsor_content_type
            if sponsor_ct.model == "group":
                from groups.models import Group

                sponsor = get_object_or_404(Group, id=lst.sponsor_object_id, is_active=True)
                allowed = PermissionService.can_user_perform_action(
                    user,
                    "can_edit_list",
                    group_slug=sponsor.slug,
                )
                if not allowed:
                    return Response(
                        {"detail": "You don't have permission to edit this list."},
                        status=status.HTTP_403_FORBIDDEN,
                    )
            else:
                if str(lst.sponsor_object_id) != str(user.id):
                    return Response(
                        {"detail": "You don't have permission to edit this list."},
                        status=status.HTTP_403_FORBIDDEN,
                    )

        # Parse, toggle, serialize
        try:
            items = parse_list_text(lst.body_text)
            items = toggle_item_completion(items, item_index)
            lst.body_text = serialize_list_items(items)
            lst.save(update_fields=["body_text", "updated_at"])
        except ValueError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(ListSerializer(lst).data)


class ListReorderView(APIView):
    """
    POST /api/lists/<id>/reorder
    Reorder a top-level item (with its children) to a new position.

    Payload:
        from_index: int - current position in top-level list (0-based)
        to_index: int - target position in top-level list (0-based)
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, list_id):
        lst = get_object_or_404(List, id=list_id, deleted_at__isnull=True)
        user = request.user

        # Permission check
        if not (user.is_staff or user.is_superuser):
            sponsor_ct = lst.sponsor_content_type
            if sponsor_ct.model == "group":
                from groups.models import Group

                sponsor = get_object_or_404(Group, id=lst.sponsor_object_id, is_active=True)
                allowed = PermissionService.can_user_perform_action(
                    user,
                    "can_edit_list",
                    group_slug=sponsor.slug,
                )
                if not allowed:
                    return Response(
                        {"detail": "You don't have permission to edit this list."},
                        status=status.HTTP_403_FORBIDDEN,
                    )
            else:
                if str(lst.sponsor_object_id) != str(user.id):
                    return Response(
                        {"detail": "You don't have permission to edit this list."},
                        status=status.HTTP_403_FORBIDDEN,
                    )

        # Validate payload
        from_index = request.data.get("from_index")
        to_index = request.data.get("to_index")

        if from_index is None or to_index is None:
            return Response(
                {"detail": "from_index and to_index are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            from_index = int(from_index)
            to_index = int(to_index)
        except (ValueError, TypeError):
            return Response(
                {"detail": "from_index and to_index must be integers."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Parse, reorder, serialize
        try:
            items = parse_list_text(lst.body_text)
            items = reorder_items(items, from_index, to_index)
            lst.body_text = serialize_list_items(items)
            lst.save(update_fields=["body_text", "updated_at"])
        except ValueError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(ListSerializer(lst).data)


class ListItemPromoteView(APIView):
    """
    POST /api/lists/<id>/promote/
    Promote a list item to a Project task.

    Payload:
        project_id: UUID - target project
        column_id: UUID (optional) - target column (defaults to Backlog)
        item_text: str - the item text to promote
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, list_id):
        from projects.models import Project, ProjectColumn, ProjectColumnSemanticType, Task

        lst = get_object_or_404(List, id=list_id, deleted_at__isnull=True)
        user = request.user

        # Permission check
        if not (user.is_staff or user.is_superuser):
            sponsor_ct = lst.sponsor_content_type
            if sponsor_ct.model == "group":
                from groups.models import Group

                sponsor = get_object_or_404(Group, id=lst.sponsor_object_id, is_active=True)
                allowed = PermissionService.can_user_perform_action(
                    user,
                    "can_edit_list",
                    group_slug=sponsor.slug,
                )
                if not allowed:
                    return Response(
                        {"detail": "You don't have permission to promote items from this list."},
                        status=status.HTTP_403_FORBIDDEN,
                    )
            else:
                if str(lst.sponsor_object_id) != str(user.id):
                    return Response(
                        {"detail": "You don't have permission to promote items from this list."},
                        status=status.HTTP_403_FORBIDDEN,
                    )

        serializer = ListItemPromoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        project_id = serializer.validated_data["project_id"]
        column_id = serializer.validated_data.get("column_id")
        item_text = serializer.validated_data["item_text"]

        # Get the project
        project = get_object_or_404(Project, id=project_id, deleted_at__isnull=True)

        # Check user has permission to add tasks to this project
        if not (user.is_staff or user.is_superuser):
            project_sponsor_ct = project.sponsor_content_type
            if project_sponsor_ct.model == "group":
                from groups.models import Group

                project_sponsor = get_object_or_404(Group, id=project.sponsor_object_id, is_active=True)
                allowed = PermissionService.can_user_perform_action(
                    user,
                    "can_edit_project",
                    group_slug=project_sponsor.slug,
                )
                if not allowed:
                    return Response(
                        {"detail": "You don't have permission to add tasks to this project."},
                        status=status.HTTP_403_FORBIDDEN,
                    )
            else:
                if str(project.sponsor_object_id) != str(user.id):
                    return Response(
                        {"detail": "You don't have permission to add tasks to this project."},
                        status=status.HTTP_403_FORBIDDEN,
                    )

        # Get target column (default to Backlog)
        if column_id:
            column = get_object_or_404(ProjectColumn, id=column_id, project=project)
        else:
            column = ProjectColumn.objects.filter(
                project=project,
                semantic_type=ProjectColumnSemanticType.BACKLOG,
            ).first()
            if not column:
                column = ProjectColumn.objects.filter(project=project).order_by("position").first()
            if not column:
                return Response(
                    {"detail": "Project has no columns."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Check if already promoted
        existing = ListItemAnnotation.find_by_text(lst, item_text)
        if existing and existing.task:
            return Response(
                {
                    "detail": "This item has already been promoted.",
                    "task_id": str(existing.task.id),
                },
                status=status.HTTP_409_CONFLICT,
            )

        # Create the task
        task = Task.create_in_column(
            project=project,
            column=column,
            title=item_text.strip(),
            submitted_by=user,
            author=user,
        )

        # Create the annotation
        annotation = ListItemAnnotation.objects.create(
            list=lst,
            item_text_hash=ListItemAnnotation.hash_item_text(item_text),
            item_text_snapshot=item_text[:500],
            task=task,
            promoted_by=user,
        )

        return Response(
            ListItemAnnotationSerializer(annotation).data,
            status=status.HTTP_201_CREATED,
        )


class ListItemAnnotationsView(APIView):
    """
    GET /api/lists/<id>/annotations/
    Get all annotations (promoted items) for a list.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, list_id):
        lst = get_object_or_404(List, id=list_id, deleted_at__isnull=True)
        user = request.user

        # Permission check (same as view)
        if not (user.is_staff or user.is_superuser):
            sponsor_ct = lst.sponsor_content_type
            if sponsor_ct.model == "group":
                from groups.models import Group

                sponsor = get_object_or_404(Group, id=lst.sponsor_object_id, is_active=True)
                allowed = PermissionService.can_user_perform_action(
                    user,
                    "can_view_list",
                    group_slug=sponsor.slug,
                )
                if not allowed:
                    return Response(
                        {"detail": "You don't have permission to view this list."},
                        status=status.HTTP_403_FORBIDDEN,
                    )
            else:
                if str(lst.sponsor_object_id) != str(user.id):
                    return Response(
                        {"detail": "You don't have permission to view this list."},
                        status=status.HTTP_403_FORBIDDEN,
                    )

        annotations = lst.annotations.select_related("task", "task__project", "promoted_by").all()
        return Response(ListItemAnnotationSerializer(annotations, many=True).data)