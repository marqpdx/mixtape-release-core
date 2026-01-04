from rest_framework import serializers

from utils.shared.contenttypes import resolve_content_type

from projects.models import Project, ProjectColumn, Task


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
        read_only_fields = [
            "id",
            "slug",
        ]

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
        fields = [
            "id",
            "title",
            "position",
            "semantic_type",
            "is_hidden",
        ]
        read_only_fields = fields


class TaskSerializer(serializers.ModelSerializer):
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
            "completed_at",
        ]
        read_only_fields = fields


class TaskCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=100)
    summary = serializers.CharField(required=False, allow_blank=True, default="")
    column_id = serializers.UUIDField(required=False)

    def validate(self, attrs):
        data = super().validate(attrs)
        project = self.context["project"]
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
        return data

    def create(self, validated_data):
        project = self.context["project"]
        column = validated_data["column"]
        return Task.create_in_column(
            project=project,
            column=column,
            title=validated_data["title"],
            summary=validated_data.get("summary", ""),
        )


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
