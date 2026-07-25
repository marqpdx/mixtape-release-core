from django.contrib import admin

from projects.models import Project, ProjectColumn, Task, TaskType


@admin.register(TaskType)
class TaskTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "is_active", "position"]
    list_editable = ["is_active", "position"]
    prepopulated_fields = {"slug": ("name",)}
    ordering = ["position", "name"]


class ProjectColumnInline(admin.TabularInline):
    model = ProjectColumn
    extra = 0
    fields = ["title", "position", "semantic_type", "is_hidden"]
    ordering = ["position"]


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["title", "mode", "archived_at", "created_at"]
    list_filter = ["mode"]
    inlines = [ProjectColumnInline]


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ["title", "project", "column", "severity", "timeliness", "assignee", "due_date", "archived_at"]
    list_filter = ["severity", "timeliness", "task_type"]
    raw_id_fields = ["assignee", "task_type"]
