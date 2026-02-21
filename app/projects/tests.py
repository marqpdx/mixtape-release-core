from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from rest_framework.test import APIClient
from django.test import TestCase

from groups.services.groups import GroupService
from groups.services.memberships import ensure_user_membership
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
        self.assertEqual([c.title for c in columns], ["Backlog", "Ready", "Doing", "Blocked", "Done"])

    def test_task_inserts_at_bottom_and_move_sets_done_state(self):
        project = self._create_project()
        backlog = project.columns.get(semantic_type="backlog")
        done = project.columns.get(semantic_type="done")
        ready = project.columns.get(semantic_type="ready")

        task1 = Task.create_in_column(project, backlog, title="First")
        task2 = Task.create_in_column(project, backlog, title="Second")
        self.assertEqual(task1.position, 0)
        self.assertEqual(task2.position, 1)

        Task.move_task(task2, done, 0)
        task2.refresh_from_db()
        self.assertIsNotNone(task2.completed_at)

        Task.move_task(task2, ready, 0)
        task2.refresh_from_db()
        self.assertIsNone(task2.completed_at)


class ProjectsApiTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="group_admin", email="admin@test.com", password="pass")
        self.member = User.objects.create_user(username="group_member", email="member@test.com", password="pass")
        self.outsider = User.objects.create_user(username="outsider", email="outsider@test.com", password="pass")
        self.staff = User.objects.create_user(
            username="staff", email="staff@test.com", password="pass", is_staff=True
        )

        self.group = GroupService.create_group(
            title="Project Group",
            group_type="community",
            created_by=self.admin,
            visibility="public",
        )
        ensure_user_membership(self.group, self.member, role="member")

        self.group_ct = ContentType.objects.get_for_model(self.group.__class__)
        self.user_ct = ContentType.objects.get_for_model(User)

        self.client = APIClient()
        self.client.raise_request_exception = False

    def _create_group_project(self, title="Group Project"):
        return Project.objects.create(
            title=title,
            sponsor_content_type=self.group_ct,
            sponsor_object_id=self.group.id,
            submitted_by=self.admin,
            author=self.admin,
        )

    def _create_user_project(self, user, title="User Project"):
        return Project.objects.create(
            title=title,
            sponsor_content_type=self.user_ct,
            sponsor_object_id=user.id,
            submitted_by=user,
            author=user,
        )

    def test_create_project_for_group_and_self_and_permissions(self):
        url = "/api/projects/projects"

        unauth = self.client.post(url, {"title": "x"}, format="json")
        self.assertEqual(unauth.status_code, 401)

        self.client.force_authenticate(self.admin)
        group_create = self.client.post(
            url,
            {
                "title": "API Group Project",
                "sponsor_content_type": "groups.Group",
                "sponsor_object_id": str(self.group.id),
            },
            format="json",
        )
        self.assertEqual(group_create.status_code, 201)
        project_id = group_create.data["id"]

        board = self.client.get(f"/api/projects/projects/{project_id}/board")
        self.assertEqual(board.status_code, 200)
        self.assertEqual(len(board.data["columns"]), 5)
        self.assertEqual([c["semantic_type"] for c in board.data["columns"]], ["backlog", "ready", "doing", "blocked", "done"])

        self.client.force_authenticate(self.outsider)
        denied = self.client.post(
            url,
            {
                "title": "Denied Group Project",
                "sponsor_content_type": "groups.Group",
                "sponsor_object_id": str(self.group.id),
            },
            format="json",
        )
        self.assertEqual(denied.status_code, 403)

        self.client.force_authenticate(self.member)
        self_project = self.client.post(
            url,
            {
                "title": "My Project",
                "sponsor_content_type": "users.CustomUser",
                "sponsor_object_id": str(self.member.id),
            },
            format="json",
        )
        self.assertEqual(self_project.status_code, 201)

    def test_project_list_filters_and_permissions(self):
        active = self._create_group_project("Active")
        archived = self._create_group_project("Archived")
        archived.archived_at = timezone.now()
        archived.save(update_fields=["archived_at"])

        url = "/api/projects/projects/list"

        self.client.force_authenticate(self.admin)
        missing = self.client.get(url)
        self.assertEqual(missing.status_code, 400)

        listed = self.client.get(
            url,
            {"sponsor_type": "groups.Group", "sponsor_object_id": str(self.group.id)},
        )
        self.assertEqual(listed.status_code, 200)
        ids = {row["id"] for row in listed.data}
        self.assertIn(str(active.id), ids)
        self.assertNotIn(str(archived.id), ids)

        self.client.force_authenticate(self.outsider)
        denied = self.client.get(
            url,
            {"sponsor_type": "groups.Group", "sponsor_object_id": str(self.group.id)},
        )
        self.assertEqual(denied.status_code, 403)

    def test_board_task_create_move_update_archive_and_toggle_hidden(self):
        project = self._create_group_project()
        backlog = project.columns.get(semantic_type="backlog")
        ready = project.columns.get(semantic_type="ready")
        done = project.columns.get(semantic_type="done")
        blocked = project.columns.get(semantic_type="blocked")

        self.client.force_authenticate(self.admin)

        board_url = f"/api/projects/projects/{project.id}/board"
        board = self.client.get(board_url)
        self.assertEqual(board.status_code, 200)
        self.assertIn("tasks_by_column", board.data)

        create_task_url = f"/api/projects/projects/{project.id}/tasks"
        t1 = self.client.post(create_task_url, {"title": "Task 1"}, format="json")
        t2 = self.client.post(create_task_url, {"title": "Task 2"}, format="json")
        self.assertEqual(t1.status_code, 201)
        self.assertEqual(t2.status_code, 201)
        self.assertLess(t1.data["position"], t2.data["position"])

        hidden_col_url = f"/api/projects/projects/{project.id}/columns/{ready.id}/toggle-hidden"
        hide_ready = self.client.patch(hidden_col_url, {}, format="json")
        self.assertEqual(hide_ready.status_code, 200)
        self.assertTrue(hide_ready.data["is_hidden"])

        create_hidden = self.client.post(
            create_task_url,
            {"title": "Nope", "column_id": str(ready.id)},
            format="json",
        )
        self.assertEqual(create_hidden.status_code, 400)

        move_hidden = self.client.post(
            f"/api/projects/tasks/{t1.data['id']}/move",
            {"to_column_id": str(ready.id), "to_index": 0},
            format="json",
        )
        self.assertEqual(move_hidden.status_code, 400)

        unhide_ready = self.client.patch(hidden_col_url, {}, format="json")
        self.assertEqual(unhide_ready.status_code, 200)
        self.assertFalse(unhide_ready.data["is_hidden"])

        mover = self.client.post(
            create_task_url,
            {"title": "Mover", "column_id": str(blocked.id)},
            format="json",
        )
        self.assertEqual(mover.status_code, 201)

        move_url = f"/api/projects/tasks/{mover.data['id']}/move"
        move_to_done = self.client.post(
            move_url,
            {"to_column_id": str(done.id), "to_index": 0},
            format="json",
        )
        self.assertEqual(move_to_done.status_code, 200)
        self.assertIn(str(done.id), move_to_done.data["columns"])
        self.assertIsNotNone(move_to_done.data["task"]["completed_at"])

        move_back = self.client.post(
            move_url,
            {"to_column_id": str(blocked.id), "to_index": 0},
            format="json",
        )
        self.assertEqual(move_back.status_code, 200)
        self.assertIsNone(move_back.data["task"]["completed_at"])

        update_url = f"/api/projects/tasks/{t1.data['id']}"
        update = self.client.patch(update_url, {"title": "Task 1 Updated", "summary": "Desc"}, format="json")
        self.assertEqual(update.status_code, 200)
        self.assertEqual(update.data["title"], "Task 1 Updated")

        empty_update = self.client.patch(update_url, {}, format="json")
        self.assertEqual(empty_update.status_code, 400)

        archive_url = f"/api/projects/tasks/{t1.data['id']}/archive"
        archive = self.client.post(archive_url, {}, format="json")
        self.assertEqual(archive.status_code, 200)

        board_after_archive = self.client.get(board_url)
        for tasks in board_after_archive.data["tasks_by_column"].values():
            self.assertTrue(all(item["id"] != t1.data["id"] for item in tasks))

        archived_move = self.client.post(
            f"/api/projects/tasks/{t1.data['id']}/move",
            {"to_column_id": str(backlog.id), "to_index": 0},
            format="json",
        )
        self.assertEqual(archived_move.status_code, 404)

    def test_toggle_hidden_column_with_tasks_rejected_and_only_archived_allowed(self):
        project = self._create_group_project("Toggle Cases")
        backlog = project.columns.get(semantic_type="backlog")

        active_task = Task.create_in_column(project, backlog, title="Active")

        self.client.force_authenticate(self.admin)
        toggle_url = f"/api/projects/projects/{project.id}/columns/{backlog.id}/toggle-hidden"
        reject = self.client.patch(toggle_url, {}, format="json")
        self.assertEqual(reject.status_code, 400)

        active_task.archived_at = timezone.now()
        active_task.save(update_fields=["archived_at"])
        allow = self.client.patch(toggle_url, {}, format="json")
        self.assertEqual(allow.status_code, 200)
        self.assertTrue(allow.data["is_hidden"])

    def test_permissions_member_staff_and_outsider(self):
        project = self._create_group_project("Permission Project")
        backlog = project.columns.get(semantic_type="backlog")
        task = Task.create_in_column(project, backlog, title="Task")

        board_url = f"/api/projects/projects/{project.id}/board"
        create_task_url = f"/api/projects/projects/{project.id}/tasks"
        update_url = f"/api/projects/tasks/{task.id}"

        self.client.force_authenticate(self.member)
        member_board = self.client.get(board_url)
        self.assertEqual(member_board.status_code, 200)
        member_create = self.client.post(create_task_url, {"title": "Member task"}, format="json")
        self.assertEqual(member_create.status_code, 201)

        self.client.force_authenticate(self.outsider)
        outsider_board = self.client.get(board_url)
        outsider_create = self.client.post(create_task_url, {"title": "No"}, format="json")
        self.assertEqual(outsider_board.status_code, 403)
        self.assertEqual(outsider_create.status_code, 403)

        self.client.force_authenticate(self.staff)
        staff_update = self.client.patch(update_url, {"title": "Staff edit"}, format="json")
        self.assertEqual(staff_update.status_code, 200)
