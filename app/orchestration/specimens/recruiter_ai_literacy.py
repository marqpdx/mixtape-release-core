from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command

from earthlab.models import Course
from groups.models import Group
from threadworks.models import Discussion, Forum

from orchestration.governed_verbs import get_governed_verb


SPECIMEN_ID = "recruiter_ai_literacy_pilot"
DEFAULT_GROUP_SLUG = "recruiter-ai-literacy"
DEFAULT_ADMIN_USERNAME = "admin"


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


def build_recruiter_ai_literacy_plan(
    *,
    group_slug: str = DEFAULT_GROUP_SLUG,
    admin_username: str = DEFAULT_ADMIN_USERNAME,
) -> InstallPlan:
    group = Group.objects.filter(slug=group_slug).first()
    admin = get_user_model().objects.filter(username=admin_username).first()
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

    steps = (
        InstallPlanStep(
            step_id="group",
            verb_id="crossroads.group.create_or_update",
            summary="Ensure the Recruiter AI Literacy group exists as a private invite-only Crossroads group.",
            current_state="exists" if group else "missing",
            intended_state="private invite-only group with recruiter pilot positioning",
            metadata={"group_slug": group_slug},
        ),
        InstallPlanStep(
            step_id="admin",
            verb_id="crossroads.group.assign_admin",
            summary="Ensure the requested operator is an owner/admin/member of the pilot group.",
            current_state="user found" if admin else "user missing",
            intended_state="admin user has owner, admin, and member roles",
            metadata={"admin_username": admin_username},
        ),
        InstallPlanStep(
            step_id="course",
            verb_id="earthlab.course.create_or_update",
            summary="Ensure the Recruiter AI Literacy EarthLab course, lessons, sequence, and course run exist.",
            current_state="exists" if course else "missing",
            intended_state="six-lesson self-paced pilot course with invite-only run",
            metadata={"course_slug": "recruiter-ai-literacy"},
        ),
        InstallPlanStep(
            step_id="forum",
            verb_id="threadworks.forum.create_or_update",
            summary="Ensure the pilot discussion forum and initial discussion spaces exist.",
            current_state=f"exists with {discussion_count} discussions" if forum else "missing",
            intended_state="group forum with introductions/questions and job-description lab notes",
            metadata={"forum_slug": "recruiter-ai-literacy"},
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
) -> None:
    args = ["--admin", admin_username, "--group-slug", group_slug]
    if draft_course:
        args.append("--draft-course")
    if skip_course:
        args.append("--skip-course")
    call_command("provision_recruiter_ai_literacy_pilot", *args)
