from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.generics import CreateAPIView

from groups.services.permissions import PermissionService
from projects.api.serializers import (
    ProjectSerializer,
    ProjectColumnSerializer,
    TaskSerializer,
    TaskCreateSerializer,
    TaskMoveSerializer,
    TaskUpdateSerializer,
)
from projects.models import Project, ProjectColumn, Task
from projects.permissions import CanArchiveTask, CanCreateTask, CanEditProject, CanEditTask, CanMoveTask, CanViewProject
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

        if not (user.is_staff or user.is_superuser):
            if sponsor_content_type.model == "group":
                from groups.models import Group
                sponsor = get_object_or_404(Group, id=sponsor_object_id, is_active=True)
                allowed = PermissionService.can_user_perform_action(
                    user,
                    "can_edit_project",
                    group_slug=sponsor.slug,
                )
                if not allowed:
                    self.permission_denied(
                        self.request,
                        message="You don't have permission to create a project for this group.",
                    )
            else:
                user_ct = ContentType.objects.get_for_model(user.__class__)
                if sponsor_content_type != user_ct or str(sponsor_object_id) != str(user.id):
                    self.permission_denied(
                        self.request,
                        message="You can only create projects for yourself.",
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

        if not (user.is_staff or user.is_superuser):
            if sponsor_content_type.model == "group":
                from groups.models import Group
                sponsor = get_object_or_404(Group, id=sponsor_object_id, is_active=True)
                allowed = PermissionService.can_user_perform_action(
                    user,
                    "can_view_project",
                    group_slug=sponsor.slug,
                )
                if not allowed:
                    self.permission_denied(
                        request,
                        message="You don't have permission to view projects for this group.",
                    )
            else:
                user_ct = ContentType.objects.get_for_model(user.__class__)
                if sponsor_content_type != user_ct or str(sponsor_object_id) != str(user.id):
                    self.permission_denied(
                        request,
                        message="You can only view your own projects.",
                    )

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

        columns = project.columns.order_by("position")
        tasks = (
            Task.objects.filter(project=project, archived_at__isnull=True)
            .order_by("column__position", "position", "created_at")
        )
        tasks_by_column = {str(column.id): [] for column in columns}
        for task in tasks:
            tasks_by_column[str(task.column_id)].append(TaskSerializer(task).data)

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

        payload = {
            "task": TaskSerializer(task).data,
            "columns": column_payload,
        }
        return Response(payload, status=status.HTTP_200_OK)


class ColumnToggleHiddenView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanEditProject]

    def patch(self, request, project_id, column_id):
        project = get_object_or_404(Project, id=project_id)
        self.check_object_permissions(request, project)

        column = get_object_or_404(ProjectColumn, id=column_id, project=project)
        column.is_hidden = not column.is_hidden
        column.save(update_fields=["is_hidden", "updated_at"])

        return Response(ProjectColumnSerializer(column).data, status=status.HTTP_200_OK)


class TaskUpdateView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanEditTask]

    def patch(self, request, task_id):
        task = get_object_or_404(Task, id=task_id, archived_at__isnull=True)
        self.check_object_permissions(request, task)

        serializer = TaskUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        for field, value in serializer.validated_data.items():
            setattr(task, field, value)
        task.save(update_fields=list(serializer.validated_data.keys()) + ["updated_at"])

        return Response(TaskSerializer(task).data, status=status.HTTP_200_OK)


class TaskArchiveView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanArchiveTask]

    def post(self, request, task_id):
        task = get_object_or_404(Task, id=task_id, archived_at__isnull=True)
        self.check_object_permissions(request, task)

        task.archived_at = timezone.now()
        task.save(update_fields=["archived_at", "updated_at"])

        return Response({"detail": "Task archived."}, status=status.HTTP_200_OK)
