from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db import transaction
from django.utils import timezone

from earthlab.choices import CourseRunStatus, CourseStatus, EnrollmentPolicy
from earthlab.models import Course
from groups.models import Group, GroupMembership
from threadworks.models import Discussion, Forum

from initiatives.models import (
    ActionRun,
    ActionRunExecutionMode,
    ActionRunInitiatorType,
    ActionRunStatus,
)
from orchestration.governed_verbs import get_governed_verb


SPECIMEN_ID = "recruiter_ai_literacy_pilot"
DEFAULT_GROUP_SLUG = "recruiter-ai-literacy"
DEFAULT_ADMIN_USERNAME = "admin"
_DEFAULT_TENANT_ID = getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", "00000000-0000-0000-0000-000000000001")
_DEFAULT_TENANT_NAMESPACE = getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", "platform:crossroads")


@dataclass(frozen=True)
class InstallPlanStep:
    step_id: str
    verb_id: str
    summary: str
    current_state: str
    intended_state: str
    requires_confirmation: bool = True
    metadata: dict[str, Any] | None = None

    @property
    def verb_label(self) -> str:
        return get_governed_verb(self.verb_id).label


@dataclass(frozen=True)
class InstallPlan:
    specimen_id: str
    title: str
    group_slug: str
    admin_username: str
    steps: tuple[InstallPlanStep, ...]


def serialize_install_plan(plan: InstallPlan) -> dict[str, Any]:
    return {
        "specimen_id": plan.specimen_id,
        "title": plan.title,
        "group_slug": plan.group_slug,
        "admin_username": plan.admin_username,
        "steps": [
            {
                "step_id": step.step_id,
                "verb_id": step.verb_id,
                "verb_label": step.verb_label,
                "summary": step.summary,
                "current_state": step.current_state,
                "intended_state": step.intended_state,
                "requires_confirmation": step.requires_confirmation,
                "metadata": step.metadata or {},
            }
            for step in plan.steps
        ],
    }


def build_recruiter_ai_literacy_plan(
    *,
    group_slug: str = DEFAULT_GROUP_SLUG,
    admin_username: str = DEFAULT_ADMIN_USERNAME,
) -> InstallPlan:
    group = Group.objects.filter(slug=group_slug).first()
    admin = get_user_model().objects.filter(username=admin_username).first()
    membership = _admin_membership(group, admin) if group and admin else None
    course = None
    forum = None
    if group:
        group_ct = ContentType.objects.get_for_model(Group)
        course = Course.objects.filter(
            sponsor_content_type=group_ct,
            sponsor_object_id=group.id,
            slug="recruiter-ai-literacy",
        ).first()
        forum = Forum.objects.filter(
            sponsor_content_type=group_ct,
            sponsor_object_id=group.id,
            slug="recruiter-ai-literacy",
        ).first()
    discussion_count = Discussion.objects.filter(forum=forum).count() if forum else 0
    discussions = list(Discussion.objects.filter(forum=forum).order_by("created_at")) if forum else []
    lesson_count = course.items.count() if course else 0
    run = course.runs.order_by("-created_at").first() if course else None

    steps = (
        InstallPlanStep(
            step_id="group",
            verb_id="crossroads.group.create_or_update",
            summary="Ensure the Recruiter AI Literacy group exists as a private invite-only Crossroads group.",
            current_state=_group_state(group),
            intended_state="private invite-only group with recruiter pilot positioning",
            metadata={
                "group_slug": group_slug,
                "target_visibility": "private",
                "target_admission_policy": "invite_only",
            },
        ),
        InstallPlanStep(
            step_id="admin",
            verb_id="crossroads.group.assign_admin",
            summary="Ensure the requested operator is an owner/admin/member of the pilot group.",
            current_state=_admin_state(admin, membership),
            intended_state="admin user has owner, admin, and member roles",
            metadata={
                "admin_username": admin_username,
                "current_roles": membership.roles if membership else [],
                "target_roles": ["member", "admin", "owner"],
            },
        ),
        InstallPlanStep(
            step_id="course",
            verb_id="earthlab.course.create_or_update",
            summary="Ensure the Recruiter AI Literacy EarthLab course, lessons, sequence, and course run exist.",
            current_state=_course_state(course, lesson_count, run),
            intended_state="six-lesson self-paced pilot course with invite-only run",
            metadata={
                "course_slug": "recruiter-ai-literacy",
                "lesson_count": lesson_count,
                "target_status": CourseStatus.PUBLISHED,
                "target_run_status": CourseRunStatus.ACTIVE,
                "target_enrollment_policy": EnrollmentPolicy.INVITE,
            },
        ),
        InstallPlanStep(
            step_id="forum",
            verb_id="threadworks.forum.create_or_update",
            summary="Ensure the pilot discussion forum and initial discussion spaces exist.",
            current_state=f"exists with {discussion_count} discussions" if forum else "missing",
            intended_state="group forum with introductions/questions and job-description lab notes",
            metadata={
                "forum_slug": "recruiter-ai-literacy",
                "discussion_titles": [discussion.title for discussion in discussions],
                "discussion_statuses": {discussion.title: discussion.status for discussion in discussions},
            },
        ),
    )

    return InstallPlan(
        specimen_id=SPECIMEN_ID,
        title="Recruiter AI Literacy Pilot Install",
        group_slug=group_slug,
        admin_username=admin_username,
        steps=steps,
    )


def execute_recruiter_ai_literacy_install(
    *,
    group_slug: str = DEFAULT_GROUP_SLUG,
    admin_username: str = DEFAULT_ADMIN_USERNAME,
    draft_course: bool = False,
    skip_course: bool = False,
) -> dict[str, Any]:
    admin = get_user_model().objects.filter(username=admin_username).first()
    before_plan = build_recruiter_ai_literacy_plan(group_slug=group_slug, admin_username=admin_username)
    action_run = ActionRun.objects.create(
        tool_name="orchestration.install.recruiter_ai_literacy",
        status=ActionRunStatus.RUNNING,
        execution_mode=ActionRunExecutionMode.LOCAL,
        service_name="orchestration",
        tenant_id=str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", _DEFAULT_TENANT_ID)),
        tenant_namespace=str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", _DEFAULT_TENANT_NAMESPACE)),
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id=str(admin.pk) if admin else admin_username,
        request_payload={
            "specimen_id": SPECIMEN_ID,
            "group_slug": group_slug,
            "admin_username": admin_username,
            "draft_course": draft_course,
            "skip_course": skip_course,
            "plan": serialize_install_plan(before_plan),
        },
    )
    try:
        args = ["--admin", admin_username, "--group-slug", group_slug]
        if draft_course:
            args.append("--draft-course")
        if skip_course:
            args.append("--skip-course")
        with transaction.atomic():
            call_command("provision_recruiter_ai_literacy_pilot", *args)
        after_plan = build_recruiter_ai_literacy_plan(group_slug=group_slug, admin_username=admin_username)
    except Exception as exc:
        action_run.status = ActionRunStatus.FAILED
        action_run.error_payload = {"error": str(exc), "type": exc.__class__.__name__}
        action_run.completed_at = timezone.now()
        action_run.save(update_fields=["status", "error_payload", "completed_at", "updated_at"])
        raise

    result = {
        "action_run_id": str(action_run.id),
        "specimen_id": SPECIMEN_ID,
        "group_slug": group_slug,
        "plan": serialize_install_plan(after_plan),
    }
    action_run.status = ActionRunStatus.SUCCEEDED
    action_run.result_payload = result
    action_run.completed_at = timezone.now()
    action_run.save(update_fields=["status", "result_payload", "completed_at", "updated_at"])
    return result


def _group_state(group: Group | None) -> str:
    if not group:
        return "missing"
    return (
        f"exists; visibility={group.visibility}; admission_policy={group.admission_policy}; "
        f"active={group.is_active}; title={group.title}"
    )


def _admin_state(admin, membership: GroupMembership | None) -> str:
    if not admin:
        return "user missing"
    if not membership:
        return "user found; no group membership"
    return (
        f"user found; roles={','.join(membership.roles or [])}; "
        f"active={membership.is_active}; pending={membership.is_pending}"
    )


def _course_state(course: Course | None, lesson_count: int, run) -> str:
    if not course:
        return "missing"
    run_state = "no run"
    if run:
        run_state = f"run={run.status}; enrollment={run.enrollment_policy}"
    return f"exists; status={course.status}; lessons={lesson_count}; {run_state}"


def _admin_membership(group: Group, admin) -> GroupMembership | None:
    user_ct = ContentType.objects.get_for_model(admin.__class__)
    return GroupMembership.objects.filter(
        group=group,
        member_content_type=user_ct,
        member_object_id=admin.pk,
    ).first()
