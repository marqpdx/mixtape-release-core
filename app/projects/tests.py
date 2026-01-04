from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APIClient

from projects.models import Project, ProjectColumn, Task


User = get_user_model()


class ProjectModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="project-owner",
            email="owner@example.com",
            password="testpass123",
        )
        self.user_ct = ContentType.objects.get_for_model(User)

    def _create_project(self):
        return Project.objects.create(
            title="Sample Project",
            sponsor_content_type=self.user_ct,
            sponsor_object_id=self.user.id,
            submitted_by=self.user,
            author=self.user,
        )

    def test_project_seeds_default_columns(self):
        project = self._create_project()
        columns = list(project.columns.order_by("position"))
        self.assertEqual(len(columns), 5)
        self.assertEqual([col.position for col in columns], [0, 1, 2, 3, 4])
        self.assertEqual(columns[0].semantic_type, "backlog")
        self.assertEqual(columns[-1].semantic_type, "done")

    def test_task_inserts_at_bottom(self):
        project = self._create_project()
        backlog = project.columns.get(semantic_type="backlog")
        task1 = Task.create_in_column(project, backlog, title="First")
        task2 = Task.create_in_column(project, backlog, title="Second")
        self.assertEqual(task1.position, 0)
        self.assertEqual(task2.position, 1)

    def test_move_within_column_reorders(self):
        project = self._create_project()
        backlog = project.columns.get(semantic_type="backlog")
        task_a = Task.create_in_column(project, backlog, title="A")
        task_b = Task.create_in_column(project, backlog, title="B")
        task_c = Task.create_in_column(project, backlog, title="C")

        Task.move_task(task_c, backlog, 0)
        ordered = list(Task.objects.filter(column=backlog).order_by("position"))
        self.assertEqual([t.id for t in ordered], [task_c.id, task_a.id, task_b.id])

    def test_move_across_columns_sets_completed_at(self):
        project = self._create_project()
        backlog = project.columns.get(semantic_type="backlog")
        done = project.columns.get(semantic_type="done")
        ready = project.columns.get(semantic_type="ready")
        task = Task.create_in_column(project, backlog, title="Finish me")

        Task.move_task(task, done, 0)
        task.refresh_from_db()
        self.assertIsNotNone(task.completed_at)

        Task.move_task(task, ready, 0)
        task.refresh_from_db()
        self.assertIsNone(task.completed_at)


class ProjectApiPermissionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner",
            email="owner@test.com",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            username="intruder",
            email="intruder@test.com",
            password="testpass123",
        )
        self.user_ct = ContentType.objects.get_for_model(User)
        self.client = APIClient()

        self.project = Project.objects.create(
            title="Private Project",
            sponsor_content_type=self.user_ct,
            sponsor_object_id=self.owner.id,
            submitted_by=self.owner,
            author=self.owner,
        )
        self.backlog = self.project.columns.get(semantic_type="backlog")
        self.ready = self.project.columns.get(semantic_type="ready")
        self.task = Task.create_in_column(self.project, self.backlog, title="Private Task")

    def test_task_move_denied_for_non_sponsor(self):
        self.client.force_authenticate(user=self.other_user)
        url = f"/api/projects/tasks/{self.task.id}/move"
        response = self.client.post(
            url,
            {"to_column_id": str(self.ready.id), "to_index": 0},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_project_list_for_member_sponsor(self):
        self.client.force_authenticate(user=self.owner)
        url = "/api/projects/projects/list"
        response = self.client.get(
            url,
            {
                "sponsor_type": "member",
                "sponsor_object_id": str(self.owner.id),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
