from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.generics import CreateAPIView

from projects.api.serializers import (
    ColumnCreateSerializer,
    ColumnUpdateSerializer,
    ProjectSerializer,
    ProjectColumnSerializer,
    TaskSerializer,
    TaskCreateSerializer,
    TaskMoveSerializer,
    TaskTypeSerializer,
    TaskTypeUpsertSerializer,
    TaskUpdateSerializer,
)
from projects.models import Project, ProjectColumn, Task, TaskType
from projects.permissions import (
    CanArchiveTask,
    CanBoardAdmin,
    CanCreateTask,
    CanEditProject,
    CanEditTask,
    CanMoveTask,
    CanViewProject,
    can_user_access_sponsor,
)
from utils.shared.contenttypes import resolve_content_type


class ProjectCreateView(CreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ProjectSerializer

    def perform_create(self, serializer):
        user = self.request.user
        sponsor_content_type = serializer.validated_data.get("sponsor_content_type")
        sponsor_object_id = serializer.validated_data.get("sponsor_object_id")

        if not sponsor_content_type:
            sponsor_content_type = ContentType.objects.get_for_model(user.__class__)
            sponsor_object_id = user.id

        if not can_user_access_sponsor(user, sponsor_content_type, sponsor_object_id, "can_edit_project"):
            self.permission_denied(
                self.request,
                message="You don't have permission to create a project for this sponsor.",
            )

        serializer.save(
            submitted_by=user,
            author=user,
            sponsor_content_type=sponsor_content_type,
            sponsor_object_id=sponsor_object_id,
        )


class ProjectListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        raw_ct = request.query_params.get("sponsor_type") or request.query_params.get("sponsor_content_type")
        sponsor_object_id = request.query_params.get("sponsor_object_id")
        if not raw_ct or not sponsor_object_id:
            return Response(
                {"detail": "sponsor_type (or sponsor_content_type) and sponsor_object_id are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sponsor_content_type = resolve_content_type(raw_ct)
        user = request.user

        if not can_user_access_sponsor(user, sponsor_content_type, sponsor_object_id, "can_view_project"):
            self.permission_denied(request, message="You don't have permission to view projects for this sponsor.")

        projects = Project.objects.filter(
            sponsor_content_type=sponsor_content_type,
            sponsor_object_id=sponsor_object_id,
            archived_at__isnull=True,
        ).order_by("-updated_at")
        return Response(ProjectSerializer(projects, many=True).data, status=status.HTTP_200_OK)


class ProjectBoardView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanViewProject]

    def get(self, request, project_id):
        project = get_object_or_404(Project, id=project_id)
        self.check_object_permissions(request, project)

        columns = project.columns.filter(is_hidden=False).order_by("position")
        tasks = (
            Task.objects.filter(project=project, archived_at__isnull=True)
            .select_related("task_type", "assignee")
            .order_by("column__position", "position", "created_at")
        )
        tasks_by_column = {str(column.id): [] for column in columns}
        for task in tasks:
            col_key = str(task.column_id)
            if col_key in tasks_by_column:
                tasks_by_column[col_key].append(TaskSerializer(task).data)

        payload = {
            "project": ProjectSerializer(project).data,
            "columns": ProjectColumnSerializer(columns, many=True).data,
            "tasks_by_column": tasks_by_column,
        }
        return Response(payload, status=status.HTTP_200_OK)


class TaskCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanCreateTask]

    def post(self, request, project_id):
        project = get_object_or_404(Project, id=project_id)
        self.check_object_permissions(request, project)

        serializer = TaskCreateSerializer(data=request.data, context={"project": project})
        serializer.is_valid(raise_exception=True)
        task = serializer.save()

        return Response(TaskSerializer(task).data, status=status.HTTP_201_CREATED)


class TaskMoveView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanMoveTask]

    def post(self, request, task_id):
        task = get_object_or_404(Task, id=task_id, archived_at__isnull=True)
        self.check_object_permissions(request, task)

        serializer = TaskMoveSerializer(data=request.data, context={"task": task})
        serializer.is_valid(raise_exception=True)

        to_column = serializer.validated_data["to_column"]
        to_index = serializer.validated_data["to_index"]
        affected_columns = Task.move_task(task, to_column, to_index)
        task.refresh_from_db()

        column_payload = {}
        for column_id in affected_columns:
            column_tasks = (
                Task.objects.filter(column_id=column_id, archived_at__isnull=True)
                .order_by("position", "created_at")
            )
            column_payload[str(column_id)] = [
                {"id": str(item.id), "position": item.position}
                for item in column_tasks
            ]

        return Response(
            {"task": TaskSerializer(task).data, "columns": column_payload},
            status=status.HTTP_200_OK,
        )


class TaskUpdateView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanEditTask]

    def patch(self, request, task_id):
        task = get_object_or_404(Task, id=task_id, archived_at__isnull=True)
        self.check_object_permissions(request, task)

        serializer = TaskUpdateSerializer(data=request.data, context={"task": task})
        serializer.is_valid(raise_exception=True)

        update_fields = list(serializer.validated_data.keys()) + ["updated_at"]
        for field, value in serializer.validated_data.items():
            setattr(task, field, value)
        task.save(update_fields=update_fields)

        task.refresh_from_db()
        return Response(TaskSerializer(task).data, status=status.HTTP_200_OK)


class TaskArchiveView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanArchiveTask]

    def post(self, request, task_id):
        task = get_object_or_404(Task, id=task_id, archived_at__isnull=True)
        self.check_object_permissions(request, task)

        task.archived_at = timezone.now()
        task.save(update_fields=["archived_at", "updated_at"])

        return Response({"detail": "Task archived."}, status=status.HTTP_200_OK)


# --- Column management (board admin only) ---

class ColumnToggleHiddenView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanEditProject]

    def patch(self, request, project_id, column_id):
        project = get_object_or_404(Project, id=project_id)
        self.check_object_permissions(request, project)

        column = get_object_or_404(ProjectColumn, id=column_id, project=project)
        column.is_hidden = not column.is_hidden
        try:
            column.save(update_fields=["is_hidden", "updated_at"])
        except ValidationError as exc:
            payload = exc.message_dict if hasattr(exc, "message_dict") else {"detail": str(exc)}
            return Response(payload, status=status.HTTP_400_BAD_REQUEST)

        return Response(ProjectColumnSerializer(column).data, status=status.HTTP_200_OK)


class ColumnUpdateView(APIView):
    """Rename or reorder a column. Board admin only."""
    permission_classes = [permissions.IsAuthenticated, CanBoardAdmin]

    def patch(self, request, project_id, column_id):
        project = get_object_or_404(Project, id=project_id)
        self.check_object_permissions(request, project)

        column = get_object_or_404(ProjectColumn, id=column_id, project=project)
        serializer = ColumnUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        new_position = serializer.validated_data.get("position")
        new_title = serializer.validated_data.get("title")

        with transaction.atomic():
            if new_title:
                column.title = new_title
            if new_position is not None and new_position != column.position:
                # Shift other columns to make room
                old_position = column.position
                cols = list(
                    ProjectColumn.objects.select_for_update()
                    .filter(project=project)
                    .exclude(pk=column.pk)
                    .order_by("position")
                )
                cols.insert(new_position, column)
                for idx, col in enumerate(cols):
                    col.position = idx
                ProjectColumn.objects.bulk_update(cols, ["position"])
                column.position = new_position
            column.save(update_fields=["title", "position", "updated_at"])

        return Response(ProjectColumnSerializer(column).data, status=status.HTTP_200_OK)


class ColumnCreateView(APIView):
    """Add a new column to a project. Board admin only."""
    permission_classes = [permissions.IsAuthenticated, CanBoardAdmin]

    def post(self, request, project_id):
        project = get_object_or_404(Project, id=project_id)
        self.check_object_permissions(request, project)

        serializer = ColumnCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        last_position = (
            ProjectColumn.objects.filter(project=project)
            .order_by("-position")
            .values_list("position", flat=True)
            .first()
        )
        position = (last_position + 1) if last_position is not None else 0

        column = ProjectColumn.objects.create(
            project=project,
            title=serializer.validated_data["title"],
            position=position,
        )
        return Response(ProjectColumnSerializer(column).data, status=status.HTTP_201_CREATED)


class ColumnDeleteView(APIView):
    """
    Delete a column. Board admin only.
    Blocked if any active tasks remain in the column — move them first.
    """
    permission_classes = [permissions.IsAuthenticated, CanBoardAdmin]

    def delete(self, request, project_id, column_id):
        project = get_object_or_404(Project, id=project_id)
        self.check_object_permissions(request, project)

        column = get_object_or_404(ProjectColumn, id=column_id, project=project)

        active_count = Task.objects.filter(column=column, archived_at__isnull=True).count()
        if active_count > 0:
            return Response(
                {
                    "detail": (
                        f"Cannot delete a column that contains {active_count} active task(s). "
                        "Move or archive them first."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        column.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- TaskType management (superuser only) ---

class TaskTypeListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        types = TaskType.objects.filter(is_active=True)
        return Response(TaskTypeSerializer(types, many=True).data)


class TaskTypeAdminView(APIView):
    """Create or update (upsert by slug) a task type. Superuser only."""
    permission_classes = [permissions.IsAdminUser]

    def post(self, request):
        serializer = TaskTypeUpsertSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task_type = serializer.save()
        return Response(TaskTypeSerializer(task_type).data, status=status.HTTP_201_CREATED)

    def patch(self, request, task_type_id):
        task_type = get_object_or_404(TaskType, id=task_type_id)
        serializer = TaskTypeUpsertSerializer(task_type, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        task_type = serializer.save()
        return Response(TaskTypeSerializer(task_type).data, status=status.HTTP_200_OK)
