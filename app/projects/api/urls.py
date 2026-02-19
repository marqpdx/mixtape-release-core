from django.urls import path

from projects.api.views import (
    ColumnToggleHiddenView,
    ProjectBoardView,
    ProjectCreateView,
    ProjectListView,
    TaskArchiveView,
    TaskCreateView,
    TaskMoveView,
    TaskUpdateView,
)


app_name = "projects"

urlpatterns = [
    path("projects", ProjectCreateView.as_view(), name="project-create"),
    path("projects/list", ProjectListView.as_view(), name="project-list"),
    path("projects/<uuid:project_id>/board", ProjectBoardView.as_view(), name="project-board"),
    path("projects/<uuid:project_id>/columns/<uuid:column_id>/toggle-hidden", ColumnToggleHiddenView.as_view(), name="column-toggle-hidden"),
    path("projects/<uuid:project_id>/tasks", TaskCreateView.as_view(), name="task-create"),
    path("tasks/<uuid:task_id>/move", TaskMoveView.as_view(), name="task-move"),
    path("tasks/<uuid:task_id>", TaskUpdateView.as_view(), name="task-update"),
    path("tasks/<uuid:task_id>/archive", TaskArchiveView.as_view(), name="task-archive"),
]
