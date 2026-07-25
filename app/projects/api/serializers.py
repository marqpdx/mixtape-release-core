from rest_framework import serializers

from utils.shared.contenttypes import resolve_content_type

from projects.models import Project, ProjectColumn, Task, TaskType
from projects.services import compute_due_date, enforce_critical_rule


class TaskTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskType
        fields = ["id", "name", "slug", "description", "is_active", "position"]
        read_only_fields = ["id"]


class TaskTypeUpsertSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskType
        fields = ["id", "name", "slug", "description", "is_active", "position"]
        read_only_fields = ["id"]

    def validate_slug(self, value):
        qs = TaskType.objects.filter(slug=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A task type with this slug already exists.")
        return value


class ProjectSerializer(serializers.ModelSerializer):
    sponsor_content_type = serializers.CharField(write_only=True, required=False)
    sponsor_object_id = serializers.UUIDField(required=False)

    class Meta:
        model = Project
        fields = [
            "id",
            "title",
            "summary",
            "body",
            "slug",
            "mode",
            "archived_at",
            "sponsor_content_type",
            "sponsor_object_id",
        ]
        read_only_fields = ["id", "slug"]

    def validate(self, attrs):
        data = super().validate(attrs)
        raw_ct = self.initial_data.get("sponsor_content_type")
        raw_obj = self.initial_data.get("sponsor_object_id")
        if raw_ct:
            if not raw_obj:
                raise serializers.ValidationError({"sponsor_object_id": "Sponsor object id is required."})
            data["sponsor_content_type"] = resolve_content_type(raw_ct)
        return data


class ProjectColumnSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectColumn
        fields = ["id", "title", "position", "semantic_type", "is_hidden"]
        read_only_fields = fields


class TaskSerializer(serializers.ModelSerializer):
    task_type = TaskTypeSerializer(read_only=True)
    assignee_id = serializers.UUIDField(source="assignee.id", read_only=True, allow_null=True)
    assignee_name = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            "id",
            "project",
            "column",
            "title",
            "summary",
            "slug",
            "position",
            "task_type",
            "severity",
            "timeliness",
            "assignee_id",
            "assignee_name",
            "sign_off_criteria",
            "due_date",
            "due_date_overridden",
            "completed_at",
        ]
        read_only_fields = fields

    def get_assignee_name(self, obj):
        if obj.assignee:
            return obj.assignee.get_full_name() or obj.assignee.username
        return None

    def get_is_overdue(self, obj):
        from datetime import date
        if obj.due_date and not obj.completed_at:
            return obj.due_date < date.today()
        return False


class TaskCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=100)
    summary = serializers.CharField(required=False, allow_blank=True, default="")
    column_id = serializers.UUIDField(required=False)
    task_type_id = serializers.UUIDField(required=False, allow_null=True)
    severity = serializers.ChoiceField(
        choices=["low", "medium", "high", "critical"],
        default="low",
    )
    timeliness = serializers.ChoiceField(
        choices=["pressing", "normal", "eventually"],
        default="normal",
    )
    assignee_id = serializers.IntegerField(required=False, allow_null=True)
    sign_off_criteria = serializers.CharField(required=False, allow_blank=True, default="")
    due_date = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs):
        data = super().validate(attrs)
        project = self.context["project"]

        # Column resolution
        column_id = data.get("column_id")
        if column_id:
            column = ProjectColumn.objects.filter(id=column_id, project=project).first()
            if not column:
                raise serializers.ValidationError({"column_id": "Column does not exist on this project."})
        else:
            column = project.columns.filter(semantic_type="backlog").first()
            if not column:
                raise serializers.ValidationError({"column_id": "Backlog column not found."})
        if column.is_hidden:
            raise serializers.ValidationError({"column_id": "Cannot add tasks to a hidden column."})
        data["column"] = column

        # TaskType
        task_type_id = data.get("task_type_id")
        if task_type_id:
            task_type = TaskType.objects.filter(id=task_type_id, is_active=True).first()
            if not task_type:
                raise serializers.ValidationError({"task_type_id": "Task type not found."})
            data["task_type"] = task_type

        # Assignee
        assignee_id = data.get("assignee_id")
        if assignee_id:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            assignee = User.objects.filter(id=assignee_id).first()
            if not assignee:
                raise serializers.ValidationError({"assignee_id": "User not found."})
            data["assignee"] = assignee

        # Critical rule: force timeliness to pressing
        severity = data["severity"]
        timeliness = enforce_critical_rule(severity, data["timeliness"])
        data["timeliness"] = timeliness

        # Due date: use provided value (marks as overridden) or auto-compute
        if "due_date" in self.initial_data and self.initial_data.get("due_date") is not None:
            data["due_date_overridden"] = True
        else:
            data["due_date"] = compute_due_date(severity, timeliness)
            data["due_date_overridden"] = False

        return data

    def create(self, validated_data):
        project = self.context["project"]
        column = validated_data["column"]
        return Task.create_in_column(
            project=project,
            column=column,
            title=validated_data["title"],
            summary=validated_data.get("summary", ""),
            task_type=validated_data.get("task_type"),
            severity=validated_data["severity"],
            timeliness=validated_data["timeliness"],
            assignee=validated_data.get("assignee"),
            sign_off_criteria=validated_data.get("sign_off_criteria", ""),
            due_date=validated_data.get("due_date"),
            due_date_overridden=validated_data.get("due_date_overridden", False),
        )


class TaskUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=100, required=False)
    summary = serializers.CharField(required=False, allow_blank=True)
    task_type_id = serializers.UUIDField(required=False, allow_null=True)
    severity = serializers.ChoiceField(
        choices=["low", "medium", "high", "critical"],
        required=False,
    )
    timeliness = serializers.ChoiceField(
        choices=["pressing", "normal", "eventually"],
        required=False,
    )
    assignee_id = serializers.IntegerField(required=False, allow_null=True)
    sign_off_criteria = serializers.CharField(required=False, allow_blank=True)
    due_date = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("At least one field is required.")

        task = self.context["task"]

        # TaskType resolution
        if "task_type_id" in attrs:
            tid = attrs.pop("task_type_id")
            if tid is None:
                attrs["task_type"] = None
            else:
                task_type = TaskType.objects.filter(id=tid, is_active=True).first()
                if not task_type:
                    raise serializers.ValidationError({"task_type_id": "Task type not found."})
                attrs["task_type"] = task_type

        # Assignee resolution
        if "assignee_id" in attrs:
            aid = attrs.pop("assignee_id")
            if aid is None:
                attrs["assignee"] = None
            else:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                assignee = User.objects.filter(id=aid).first()
                if not assignee:
                    raise serializers.ValidationError({"assignee_id": "User not found."})
                attrs["assignee"] = assignee

        # Resolve final severity and timeliness (use task's current values as fallback)
        severity = attrs.get("severity", task.severity)
        timeliness_raw = attrs.get("timeliness", task.timeliness)
        timeliness = enforce_critical_rule(severity, timeliness_raw)

        severity_changed = "severity" in attrs and attrs["severity"] != task.severity
        timeliness_changed = timeliness != task.timeliness

        attrs["severity"] = severity
        attrs["timeliness"] = timeliness

        # Due date logic
        if "due_date" in self.initial_data:
            # User explicitly set (or cleared) the date — mark as overridden
            attrs["due_date_overridden"] = True
        elif (severity_changed or timeliness_changed) and not task.due_date_overridden:
            # Timeliness/severity changed and date was never manually set — recalculate
            attrs["due_date"] = compute_due_date(severity, timeliness)

        return attrs


class TaskMoveSerializer(serializers.Serializer):
    to_column_id = serializers.UUIDField()
    to_index = serializers.IntegerField(min_value=0)

    def validate(self, attrs):
        data = super().validate(attrs)
        task = self.context["task"]
        to_column = ProjectColumn.objects.filter(
            id=data["to_column_id"],
            project=task.project,
        ).first()
        if not to_column:
            raise serializers.ValidationError({"to_column_id": "Column does not exist on this project."})
        if to_column.is_hidden:
            raise serializers.ValidationError({"to_column_id": "Cannot move tasks into a hidden column."})
        data["to_column"] = to_column
        return data


class ColumnUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=120, required=False)
    position = serializers.IntegerField(min_value=0, required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("At least one field (title, position) is required.")
        return attrs


class ColumnCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=120)
