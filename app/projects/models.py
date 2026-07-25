# projects/models.py

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from fundamentals.models import BaseContent, BaseData, BaseModel


class ProjectMode(models.TextChoices):
    LIST = "list", "List"
    PROJECT = "project", "Project"


class ProjectColumnSemanticType(models.TextChoices):
    BACKLOG = "backlog", "Backlog"
    READY = "ready", "Ready"
    DOING = "doing", "Doing"        # legacy — kept for existing boards
    STARTED = "started", "Started"
    NEEDS_REVIEW = "needs_review", "Needs Review"
    BLOCKED = "blocked", "Blocked"  # legacy — kept for existing boards
    DONE = "done", "Done"


class TaskSeverity(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    CRITICAL = "critical", "Critical"


class TaskTimeliness(models.TextChoices):
    PRESSING = "pressing", "Pressing"
    NORMAL = "normal", "Normal"
    EVENTUALLY = "eventually", "Eventually"


class TaskType(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "name"]

    def __str__(self):
        return self.name


class Project(BaseContent):
    """
    Lightweight container for tasks and columns.
    """
    mode = models.CharField(
        max_length=20,
        choices=ProjectMode.choices,
        default=ProjectMode.LIST,
    )
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseContent.Meta):
        ordering = ["-updated_at"]
        indexes = BaseContent.Meta.indexes + [
            models.Index(fields=["mode", "-updated_at"]),
        ]

    def __str__(self):
        return self.title or f"Project {self.pk}"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new:
            ProjectColumn.seed_defaults(self)


class ProjectColumn(BaseModel):
    """
    Ordered columns for a project board.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="columns")
    title = models.CharField(max_length=120)
    position = models.PositiveIntegerField()
    semantic_type = models.CharField(
        max_length=20,
        choices=ProjectColumnSemanticType.choices,
        null=True,
        blank=True,
    )
    is_hidden = models.BooleanField(default=False)

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "position"],
                name="projects_projectcolumn_project_position_unique",
            ),
            models.UniqueConstraint(
                fields=["project", "semantic_type"],
                condition=models.Q(semantic_type__isnull=False),
                name="projects_projectcolumn_project_semantic_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["project", "position"]),
            models.Index(fields=["project", "semantic_type"]),
        ]

    def __str__(self):
        return f"{self.project}: {self.title}"

    def clean(self):
        if self.is_hidden and self.pk:
            has_tasks = self.tasks.filter(archived_at__isnull=True).exists()
            if has_tasks:
                raise ValidationError({"is_hidden": "Cannot hide a column that contains tasks."})

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    @classmethod
    def seed_defaults(cls, project):
        defaults = [
            ("Backlog", ProjectColumnSemanticType.BACKLOG),
            ("Ready", ProjectColumnSemanticType.READY),
            ("Started", ProjectColumnSemanticType.STARTED),
            ("Needs Review", ProjectColumnSemanticType.NEEDS_REVIEW),
            ("Done", ProjectColumnSemanticType.DONE),
        ]
        columns = [
            cls(
                project=project,
                title=title,
                position=idx,
                semantic_type=semantic_type,
            )
            for idx, (title, semantic_type) in enumerate(defaults)
        ]
        cls.objects.bulk_create(columns)


class Task(BaseData):
    """
    Item of work inside a project column.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    column = models.ForeignKey(ProjectColumn, on_delete=models.CASCADE, related_name="tasks")
    position = models.PositiveIntegerField()
    completed_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    task_type = models.ForeignKey(
        TaskType,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tasks",
    )
    severity = models.CharField(
        max_length=20,
        choices=TaskSeverity.choices,
        default=TaskSeverity.LOW,
    )
    timeliness = models.CharField(
        max_length=20,
        choices=TaskTimeliness.choices,
        default=TaskTimeliness.NORMAL,
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_tasks",
    )
    sign_off_criteria = models.TextField(blank=True, default="")
    due_date = models.DateField(null=True, blank=True)
    due_date_overridden = models.BooleanField(default=False)

    class Meta:
        ordering = ["position", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["column", "position"],
                name="projects_task_column_position_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["project", "column", "position"]),
        ]

    def __str__(self):
        return self.title or f"Task {self.pk}"

    @classmethod
    def next_position_for_column(cls, column):
        last = (
            cls.objects.select_for_update()
            .filter(column=column, archived_at__isnull=True)
            .order_by("-position")
            .first()
        )
        return (last.position + 1) if last else 0

    @classmethod
    def create_in_column(cls, project, column, title, summary="", **kwargs):
        with transaction.atomic():
            position = cls.next_position_for_column(column)
            task = cls.objects.create(
                project=project,
                column=column,
                position=position,
                title=title,
                summary=summary,
                **kwargs,
            )
            if column.semantic_type == ProjectColumnSemanticType.DONE:
                task.completed_at = timezone.now()
                task.save(update_fields=["completed_at"])
            return task

    @classmethod
    def _reindex(cls, tasks):
        if not tasks:
            return
        offset = 1000000
        for idx, task in enumerate(tasks):
            task.position = offset + idx
        cls.objects.bulk_update(tasks, ["position"])
        for idx, task in enumerate(tasks):
            task.position = idx
        cls.objects.bulk_update(tasks, ["position"])

    @classmethod
    def move_task(cls, task, to_column, to_index):
        if to_column.is_hidden:
            raise ValidationError({"to_column_id": "Cannot move tasks into a hidden column."})

        with transaction.atomic():
            source_column = task.column
            if source_column.id == to_column.id:
                tasks = list(
                    cls.objects.filter(column=to_column, archived_at__isnull=True)
                    .order_by("position", "created_at", "id")
                )
                tasks = [t for t in tasks if t.id != task.id]
                bounded_index = max(0, min(to_index, len(tasks)))
                tasks.insert(bounded_index, task)

                if to_column.semantic_type == ProjectColumnSemanticType.DONE and task.completed_at is None:
                    task.completed_at = timezone.now()
                if to_column.semantic_type != ProjectColumnSemanticType.DONE:
                    task.completed_at = None

                cls._reindex(tasks)
                cls.objects.filter(pk=task.pk).update(
                    position=task.position,
                    completed_at=task.completed_at,
                )
                return [to_column.id]

            source_tasks = list(
                cls.objects.filter(column=source_column, archived_at__isnull=True)
                .order_by("position", "created_at", "id")
            )
            source_tasks = [t for t in source_tasks if t.id != task.id]

            target_tasks = list(
                cls.objects.filter(column=to_column, archived_at__isnull=True)
                .order_by("position", "created_at", "id")
            )
            bounded_index = max(0, min(to_index, len(target_tasks)))

            task.column = to_column
            if to_column.semantic_type == ProjectColumnSemanticType.DONE:
                task.completed_at = timezone.now()
            else:
                task.completed_at = None
            task.position = 1000000
            task.save(update_fields=["column", "position", "completed_at"])

            target_tasks.insert(bounded_index, task)

            cls._reindex(source_tasks)
            cls._reindex(target_tasks)
            cls.objects.bulk_update(
                target_tasks,
                ["position", "column", "completed_at"],
            )
            return [source_column.id, to_column.id]
