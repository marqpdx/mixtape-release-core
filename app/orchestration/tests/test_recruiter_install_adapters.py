from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from earthlab.choices import CourseRunStatus, CourseStatus, EnrollmentPolicy
from earthlab.models import Course
from groups.models import Group, GroupMembership
from groups.models.dec_enums import AdmissionPolicy, GroupVisibility
from initiatives.models import ActionRun, ActionRunStatus
from orchestration.governed_verbs.adapters import provision_recruiter_ai_literacy_install
from orchestration.specimens.recruiter_ai_literacy import execute_recruiter_ai_literacy_install
from threadworks.models import Discussion, Forum


class RecruiterInstallAdapterTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(
            username="admin",
            email="admin@example.com",
            password="test-pass",
            is_staff=True,
            is_superuser=True,
        )

    def test_provision_recruiter_install_is_idempotent(self):
        first = provision_recruiter_ai_literacy_install(admin_username=self.admin.username)
        second = provision_recruiter_ai_literacy_install(admin_username=self.admin.username)

        self.assertTrue(first["group"].created)
        self.assertFalse(second["group"].created)

        group = Group.objects.get(slug="recruiter-ai-literacy")
        self.assertEqual(group.visibility, GroupVisibility.PRIVATE)
        self.assertEqual(group.admission_policy, AdmissionPolicy.INVITE_ONLY)
        self.assertTrue(group.is_active)

        user_ct = ContentType.objects.get_for_model(self.admin.__class__)
        membership = GroupMembership.objects.get(
            group=group,
            member_content_type=user_ct,
            member_object_id=self.admin.pk,
        )
        self.assertEqual(membership.roles, ["member", "admin", "owner"])
        self.assertTrue(membership.is_active)
        self.assertFalse(membership.is_pending)

        group_ct = ContentType.objects.get_for_model(Group)
        course = Course.objects.get(
            sponsor_content_type=group_ct,
            sponsor_object_id=group.id,
            slug="recruiter-ai-literacy",
        )
        self.assertEqual(course.status, CourseStatus.PUBLISHED)
        self.assertEqual(course.items.count(), 6)
        run = course.runs.get(title="Recruiter AI Literacy Pilot")
        self.assertEqual(run.status, CourseRunStatus.ACTIVE)
        self.assertEqual(run.enrollment_policy, EnrollmentPolicy.INVITE)

        forum = Forum.objects.get(
            sponsor_content_type=group_ct,
            sponsor_object_id=group.id,
            slug="recruiter-ai-literacy",
        )
        self.assertEqual(Discussion.objects.filter(forum=forum).count(), 2)

    def test_execute_recruiter_install_records_action_run(self):
        result = execute_recruiter_ai_literacy_install(admin_username=self.admin.username)

        action_run = ActionRun.objects.get(id=result["action_run_id"])
        self.assertEqual(action_run.status, ActionRunStatus.SUCCEEDED)
        self.assertEqual(action_run.tool_name, "orchestration.install.recruiter_ai_literacy")
        self.assertEqual(action_run.result_payload["specimen_id"], "recruiter_ai_literacy_pilot")
