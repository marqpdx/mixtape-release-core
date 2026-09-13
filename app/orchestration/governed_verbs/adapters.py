from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import CommandError
from django.db import transaction

from earthlab.choices import (
    CourseRunStatus,
    CourseStatus,
    DeliveryType,
    DifficultyLevel,
    EnrollmentPolicy,
    LessonStatus,
)
from earthlab.models import Course, CourseItem, CourseRun, Lesson
from groups.models import Group, GroupMembership
from groups.models.dec_enums import AdmissionPolicy, GroupType, GroupVisibility
from groups.services.groups import GroupService
from groups.services.permission_profiles import assign_default_permission_profile
from threadworks.models import Discussion, Forum


RECRUITER_AI_LITERACY_GROUP_SLUG = "recruiter-ai-literacy"
RECRUITER_AI_LITERACY_GROUP_TITLE = "Recruiter AI Literacy"
RECRUITER_AI_LITERACY_COURSE_SLUG = "recruiter-ai-literacy"
RECRUITER_AI_LITERACY_COURSE_TITLE = "Recruiter AI Literacy"
RECRUITER_AI_LITERACY_FORUM_SLUG = "recruiter-ai-literacy"


@dataclass(frozen=True)
class AdapterResult:
    obj: Any
    created: bool
    details: dict[str, Any]


RECRUITER_AI_LITERACY_LESSONS: tuple[dict[str, Any], ...] = (
    {
        "slug": "ai-isnt-one-thing",
        "title": "AI Is Not One Thing",
        "summary": "Separate the modern tool landscape into usable parts instead of treating AI as one monolith.",
        "minutes": 12,
        "body": """# AI Is Not One Thing

AI is a label placed over many different capacities: transcription, embeddings, search by meaning, local language models, cloud models, classification, image recognition, agents, deterministic software, databases, and APIs.

The practical question is not whether something is AI. The practical questions are:

- What kind of work is being done?
- What information does it need?
- What can be checked?
- What should a person decide?
- What tool is proportionate?

For a recruiter, this matters because a technical job description may mention twenty unfamiliar tools. The job is not to memorize them all. The job is to learn how to investigate them carefully enough to have a useful conversation.
""",
    },
    {
        "slug": "language-becomes-an-interface",
        "title": "Language Becomes an Interface",
        "summary": "Learn the shift from operating software procedures toward expressing intent clearly.",
        "minutes": 14,
        "body": """# Language Becomes an Interface

For decades, using software meant learning menus, fields, commands, folders, and workflows. Those remain useful, but they are no longer the only way to work.

Modern language tools let people state intent in ordinary language. That does not remove structure. It makes structure more important.

In Crossroads terms:

> Natural language expresses intent; Shapes constrain interpretation; governed verbs perform the work.

The discipline is learning to say what you mean, then checking whether the system understood the work correctly.
""",
    },
    {
        "slug": "anatomy-of-a-technical-job-description",
        "title": "Anatomy of a Technical Job Description",
        "summary": "Break a technical job description into terms, relationships, requirements, and open questions.",
        "minutes": 20,
        "body": """# Anatomy of a Technical Job Description

A technical job description is usually a compressed map of a working environment.

Useful questions:

- Which words are languages, databases, frameworks, protocols, vendors, infrastructure, practices, or job duties?
- Which requirements are essential?
- Which requirements are ornamental or copied from a template?
- Which technologies normally appear together?
- What does this imply about the team, product, stack, and maturity?
- What should the recruiter ask the hiring manager before contacting candidates?

The goal is not instant expertise. The goal is a better investigation.
""",
    },
    {
        "slug": "working-with-what-you-do-not-know",
        "title": "Working With What You Do Not Know",
        "summary": "Practice asking, comparing, challenging, verifying, and identifying uncertainty.",
        "minutes": 18,
        "body": """# Working With What You Do Not Know

Good information work does not pretend uncertainty away.

When you meet unfamiliar material, work in passes:

1. List important terms.
2. Group related terms.
3. Ask what each term does in plain language.
4. Compare explanations from more than one source.
5. Identify what seems central, optional, or unclear.
6. Bring better questions back to a human expert.

A language tool can help you move faster through the first pass. It should not replace your judgment.
""",
    },
    {
        "slug": "common-information-challenges",
        "title": "Common Information Challenges",
        "summary": "See how Mixtape and Catalyst frame meaning, provenance, provisional findings, and trusted knowledge.",
        "minutes": 16,
        "body": """# Common Information Challenges

Most teams have information in many places: inboxes, spreadsheets, files, memories, chat threads, old websites, and half-finished notes.

The hard part is not only finding more information. The hard part is knowing what is current, what is trustworthy, what still needs review, and what your organization stands behind.

Mixtape and Catalyst approach this through:

- finding by meaning;
- preserving provenance;
- separating provisional findings from trusted knowledge;
- using Shapes for recurring kinds of things;
- combining local and cloud tooling proportionately;
- keeping human judgment at the center.
""",
    },
    {
        "slug": "applied-job-description-lab",
        "title": "Applied Job Description Lab",
        "summary": "Apply the investigation pattern to several real technical job descriptions.",
        "minutes": 30,
        "body": """# Applied Job Description Lab

In the lab, use real job descriptions from different technical domains.

For each one:

- extract the important terms;
- identify the technology categories;
- sketch how the terms relate;
- name what seems essential;
- name what needs verification;
- write three questions for the hiring manager;
- write a plain-language summary for a recruiter.

The outcome is not a perfect technical taxonomy. The outcome is a recruiter who can move through unfamiliar material with more confidence, precision, and humility.
""",
    },
)


def get_user_by_username(username: str):
    user = get_user_model().objects.filter(username=username).first()
    if not user:
        raise CommandError(f"User not found: {username}")
    return user


def create_or_update_recruiter_ai_literacy_group(*, admin, group_slug: str) -> AdapterResult:
    group = Group.objects.filter(slug=group_slug).first()
    created = False
    if not group:
        group = GroupService.create_group(
            title=RECRUITER_AI_LITERACY_GROUP_TITLE,
            group_type=GroupType.COMMUNITY,
            created_by=admin,
            description=(
                "A bounded learning group for recruiters practicing careful investigation "
                "of unfamiliar technical material with modern language tools."
            ),
            summary=(
                "A small recruiter-focused Crossroads pilot for AI literacy, technical "
                "job-description analysis, and human-centered information work."
            ),
            visibility=GroupVisibility.PRIVATE,
            slug=group_slug,
        )
        created = True

    group.title = RECRUITER_AI_LITERACY_GROUP_TITLE
    group.description = (
        "A bounded learning group for recruiters practicing careful investigation "
        "of unfamiliar technical material with modern language tools."
    )
    group.summary = (
        "A small recruiter-focused Crossroads pilot for AI literacy, technical "
        "job-description analysis, and human-centered information work."
    )
    group.tagline = "Learn to investigate technical work with clarity, caution, and confidence."
    group.group_type = GroupType.COMMUNITY
    group.visibility = GroupVisibility.PRIVATE
    group.admission_policy = AdmissionPolicy.INVITE_ONLY
    group.is_active = True
    group.escrow_owner = group.escrow_owner or admin
    group.save(
        update_fields=[
            "title",
            "description",
            "summary",
            "tagline",
            "group_type",
            "visibility",
            "admission_policy",
            "is_active",
            "escrow_owner",
            "updated_at",
        ]
    )
    return AdapterResult(
        obj=group,
        created=created,
        details={
            "group_slug": group.slug,
            "visibility": group.visibility,
            "admission_policy": group.admission_policy,
        },
    )


def assign_recruiter_ai_literacy_admin(*, group: Group, admin) -> AdapterResult:
    user_ct = ContentType.objects.get_for_model(admin.__class__)
    membership, created = GroupMembership.objects.get_or_create(
        group=group,
        member_content_type=user_ct,
        member_object_id=admin.pk,
        defaults={
            "roles": ["member", "admin", "owner"],
            "is_active": True,
            "is_pending": False,
        },
    )
    if created:
        assign_default_permission_profile(membership, assigned_by=admin)

    changed = False
    desired_roles = ["member", "admin", "owner"]
    for role in desired_roles:
        if role not in membership.roles:
            membership.roles.append(role)
            changed = True
    if membership.is_pending or not membership.is_active:
        membership.is_pending = False
        membership.is_active = True
        changed = True
    if changed:
        membership.save(update_fields=["roles", "is_pending", "is_active", "updated_at"])

    return AdapterResult(
        obj=membership,
        created=created,
        details={"roles": membership.roles, "is_active": membership.is_active, "is_pending": membership.is_pending},
    )


def create_or_update_recruiter_ai_literacy_forum(*, group: Group, admin) -> AdapterResult:
    group_ct = ContentType.objects.get_for_model(group.__class__)
    forum, created = Forum.objects.update_or_create(
        sponsor_content_type=group_ct,
        sponsor_object_id=group.id,
        slug=RECRUITER_AI_LITERACY_FORUM_SLUG,
        defaults={
            "title": "Recruiter AI Literacy",
            "slug_is_custom": True,
            "summary": "Questions and reflections for the Recruiter AI Literacy pilot.",
            "description": (
                "A bounded discussion space for course questions, job-description lab notes, "
                "and practical reflections from the recruiter AI literacy pilot."
            ),
            "visibility": "group",
            "audience_type": "all_members",
            "auto_add_new_members": True,
            "is_archived": False,
        },
    )
    discussions = create_or_update_recruiter_ai_literacy_discussions(forum=forum, admin=admin)
    return AdapterResult(
        obj=forum,
        created=created,
        details={
            "forum_slug": forum.slug,
            "discussion_titles": [discussion.title for discussion in discussions],
        },
    )


def create_or_update_recruiter_ai_literacy_discussions(*, forum: Forum, admin) -> list[Discussion]:
    specs = [
        {
            "slug": "introductions-and-questions",
            "title": "Introductions and questions",
            "description": (
                "Say hello, name the kinds of roles or job descriptions you work with, "
                "and leave questions as you move through the course."
            ),
            "status": "pinned",
            "pinned_nav_name": "Questions",
        },
        {
            "slug": "job-description-lab-notes",
            "title": "Job-description lab notes",
            "description": (
                "Use this thread for notes from real technical job descriptions: unclear terms, "
                "candidate questions, hiring-manager questions, and verification gaps."
            ),
            "status": "active",
            "pinned_nav_name": "",
        },
    ]
    discussions = []
    for spec in specs:
        discussion, _ = Discussion.objects.update_or_create(
            forum=forum,
            slug=spec["slug"],
            defaults={
                "title": spec["title"],
                "slug_is_custom": True,
                "description": spec["description"],
                "status": spec["status"],
                "pinned_nav_name": spec["pinned_nav_name"],
                "visibility_scope": "group",
                "created_by": admin,
                "is_locked": False,
                "is_deleted": False,
            },
        )
        discussions.append(discussion)
    return discussions


def create_or_update_recruiter_ai_literacy_course(
    *,
    group: Group,
    author,
    draft: bool = False,
) -> AdapterResult:
    group_ct = ContentType.objects.get_for_model(Group)
    lesson_ct = ContentType.objects.get_for_model(Lesson)
    status = CourseStatus.DRAFT if draft else CourseStatus.PUBLISHED
    lesson_status = LessonStatus.DRAFT if draft else LessonStatus.PUBLISHED

    course, course_created = Course.objects.get_or_create(
        sponsor_content_type=group_ct,
        sponsor_object_id=group.id,
        slug=RECRUITER_AI_LITERACY_COURSE_SLUG,
        defaults={
            "title": RECRUITER_AI_LITERACY_COURSE_TITLE,
            "slug_is_custom": True,
            "summary": (
                "A small recruiter-focused course on doing careful information work "
                "with modern language tools and technical job descriptions."
            ),
            "body": (
                "This pilot gives recruiters a bounded first experience of Crossroads "
                "through EarthLab. It teaches investigation, verification, and judgment "
                "rather than generic prompt tricks."
            ),
            "status": status,
            "difficulty_level": DifficultyLevel.BEGINNER,
            "delivery_type": DeliveryType.SELF_PACED,
            "estimated_duration": sum(item["minutes"] for item in RECRUITER_AI_LITERACY_LESSONS),
            "learning_objectives": [
                "Distinguish different kinds of AI and information tooling.",
                "Break down unfamiliar technical job descriptions with more confidence.",
                "Separate confident findings from claims requiring verification.",
                "Use language tools without surrendering human judgment.",
            ],
            "author": author,
            "submitted_by": author,
        },
    )
    if not course_created:
        course.title = RECRUITER_AI_LITERACY_COURSE_TITLE
        course.slug_is_custom = True
        course.summary = (
            "A small recruiter-focused course on doing careful information work "
            "with modern language tools and technical job descriptions."
        )
        course.body = (
            "This pilot gives recruiters a bounded first experience of Crossroads "
            "through EarthLab. It teaches investigation, verification, and judgment "
            "rather than generic prompt tricks."
        )
        course.status = status
        course.difficulty_level = DifficultyLevel.BEGINNER
        course.delivery_type = DeliveryType.SELF_PACED
        course.estimated_duration = sum(item["minutes"] for item in RECRUITER_AI_LITERACY_LESSONS)
        course.learning_objectives = [
            "Distinguish different kinds of AI and information tooling.",
            "Break down unfamiliar technical job descriptions with more confidence.",
            "Separate confident findings from claims requiring verification.",
            "Use language tools without surrendering human judgment.",
        ]
        if author and not course.author_id:
            course.author = author
        if author and not course.submitted_by_id:
            course.submitted_by = author
        course.save()

    lessons = []
    for entry in RECRUITER_AI_LITERACY_LESSONS:
        lesson, _ = Lesson.objects.update_or_create(
            sponsor_content_type=group_ct,
            sponsor_object_id=group.id,
            slug=entry["slug"],
            defaults={
                "title": entry["title"],
                "slug_is_custom": True,
                "summary": entry["summary"],
                "body": entry["body"],
                "status": lesson_status,
                "difficulty_level": DifficultyLevel.BEGINNER,
                "estimated_duration": entry["minutes"],
                "author": author,
                "submitted_by": author,
            },
        )
        lessons.append(lesson)

    for offset, lesson in enumerate(lessons, start=1):
        CourseItem.objects.filter(
            course=course,
            content_type=lesson_ct,
            content_object_id=lesson.id,
        ).update(position=1000 + offset)

    for index, lesson in enumerate(lessons, start=1):
        item, _ = CourseItem.objects.get_or_create(
            course=course,
            content_type=lesson_ct,
            content_object_id=lesson.id,
            defaults={"position": index, "section_title": "Recruiter AI Literacy Pilot"},
        )
        item.position = index
        item.section_title = "Recruiter AI Literacy Pilot"
        item.save(update_fields=["position", "section_title", "updated_at"])

    CourseRun.objects.update_or_create(
        course=course,
        title="Recruiter AI Literacy Pilot",
        defaults={
            "status": CourseRunStatus.ACTIVE,
            "enrollment_policy": EnrollmentPolicy.INVITE,
            "max_enrollment": None,
        },
    )

    return AdapterResult(
        obj=course,
        created=course_created,
        details={
            "course_slug": course.slug,
            "lesson_count": len(lessons),
            "status": course.status,
        },
    )


def provision_recruiter_ai_literacy_install(
    *,
    admin_username: str,
    group_slug: str = RECRUITER_AI_LITERACY_GROUP_SLUG,
    draft_course: bool = False,
    skip_course: bool = False,
) -> dict[str, AdapterResult]:
    admin = get_user_by_username(admin_username)
    with transaction.atomic():
        group_result = create_or_update_recruiter_ai_literacy_group(admin=admin, group_slug=group_slug)
        group = group_result.obj
        membership_result = assign_recruiter_ai_literacy_admin(group=group, admin=admin)
        forum_result = create_or_update_recruiter_ai_literacy_forum(group=group, admin=admin)
        course_result = None
        if not skip_course:
            course_result = create_or_update_recruiter_ai_literacy_course(
                group=group,
                author=admin,
                draft=draft_course,
            )

    result = {
        "group": group_result,
        "membership": membership_result,
        "forum": forum_result,
    }
    if course_result:
        result["course"] = course_result
    return result
