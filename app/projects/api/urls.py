from django.urls import path

from projects.api.views import (
    ColumnCreateView,
    ColumnDeleteView,
    ColumnToggleHiddenView,
    ColumnUpdateView,
    ProjectBoardView,
    ProjectCreateView,
    ProjectListView,
    TaskArchiveView,
    TaskCreateView,
    TaskMoveView,
    TaskTypeAdminView,
    TaskTypeListView,
    TaskUpdateView,
)


app_name = "projects"

urlpatterns = [
    # Projects
    path("projects", ProjectCreateView.as_view(), name="project-create"),
    path("projects/list", ProjectListView.as_view(), name="project-list"),
    path("projects/<uuid:project_id>/board", ProjectBoardView.as_view(), name="project-board"),

    # Tasks
    path("projects/<uuid:project_id>/tasks", TaskCreateView.as_view(), name="task-create"),
    path("tasks/<uuid:task_id>/move", TaskMoveView.as_view(), name="task-move"),
    path("tasks/<uuid:task_id>", TaskUpdateView.as_view(), name="task-update"),
    path("tasks/<uuid:task_id>/archive", TaskArchiveView.as_view(), name="task-archive"),

    # Column management (board admin)
    path("projects/<uuid:project_id>/columns", ColumnCreateView.as_view(), name="column-create"),
    path("projects/<uuid:project_id>/columns/<uuid:column_id>", ColumnUpdateView.as_view(), name="column-update"),
    path("projects/<uuid:project_id>/columns/<uuid:column_id>/delete", ColumnDeleteView.as_view(), name="column-delete"),
    path("projects/<uuid:project_id>/columns/<uuid:column_id>/toggle-hidden", ColumnToggleHiddenView.as_view(), name="column-toggle-hidden"),

    # Task types
    path("task-types", TaskTypeListView.as_view(), name="task-type-list"),
    path("task-types/admin", TaskTypeAdminView.as_view(), name="task-type-admin-create"),
    path("task-types/admin/<uuid:task_type_id>", TaskTypeAdminView.as_view(), name="task-type-admin-update"),
]
