from django.urls import path

from projects.api.views import ProjectBoardView, ProjectCreateView, ProjectListView, TaskCreateView, TaskMoveView


app_name = "projects"

urlpatterns = [
    path("projects", ProjectCreateView.as_view(), name="project-create"),
    path("projects/list", ProjectListView.as_view(), name="project-list"),
    path("projects/<uuid:project_id>/board", ProjectBoardView.as_view(), name="project-board"),
    path("projects/<uuid:project_id>/tasks", TaskCreateView.as_view(), name="task-create"),
    path("tasks/<uuid:task_id>/move", TaskMoveView.as_view(), name="task-move"),
]
