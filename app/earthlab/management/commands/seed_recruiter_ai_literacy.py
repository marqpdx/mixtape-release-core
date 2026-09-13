"""
Seed the Recruiter AI Literacy pilot course for a group.

Usage:
    python manage.py seed_recruiter_ai_literacy mindful-brilliance
    python manage.py seed_recruiter_ai_literacy mindful-brilliance --username admin
"""

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from earthlab.choices import CourseRunStatus, CourseStatus, DeliveryType, DifficultyLevel, EnrollmentPolicy, LessonStatus
from earthlab.models import Course, CourseItem, CourseRun, Lesson
from groups.models import Group


COURSE_SLUG = "recruiter-ai-literacy"
COURSE_TITLE = "Recruiter AI Literacy"

LESSONS = [
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
]


class Command(BaseCommand):
    help = "Seed the Recruiter AI Literacy pilot EarthLab course for a group. Idempotent."

    def add_arguments(self, parser):
        parser.add_argument("group_slug", help="Group slug that should sponsor the course.")
        parser.add_argument(
            "--username",
            default="",
            help="Optional author/submitted_by username. Defaults to the first superuser, then first user.",
        )
        parser.add_argument(
            "--draft",
            action="store_true",
            help="Seed course and lessons as draft instead of published.",
        )

    def handle(self, *args, **options):
        group_slug = options["group_slug"]
        group = Group.objects.filter(slug=group_slug).first()
        if not group:
            raise CommandError(f"Group not found: {group_slug}")

        author = self._resolve_author(options["username"])
        group_ct = ContentType.objects.get_for_model(Group)
        lesson_ct = ContentType.objects.get_for_model(Lesson)
        status = CourseStatus.DRAFT if options["draft"] else CourseStatus.PUBLISHED
        lesson_status = LessonStatus.DRAFT if options["draft"] else LessonStatus.PUBLISHED

        with transaction.atomic():
            course, course_created = Course.objects.get_or_create(
                sponsor_content_type=group_ct,
                sponsor_object_id=group.id,
                slug=COURSE_SLUG,
                defaults={
                    "title": COURSE_TITLE,
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
                    "estimated_duration": sum(item["minutes"] for item in LESSONS),
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
                course.title = COURSE_TITLE
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
                course.estimated_duration = sum(item["minutes"] for item in LESSONS)
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
            for entry in LESSONS:
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

        action = "created" if course_created else "updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"Recruiter AI Literacy course {action} for {group.slug}: "
                f"{len(lessons)} lessons, slug={COURSE_SLUG}"
            )
        )

    def _resolve_author(self, username):
        User = get_user_model()
        if username:
            user = User.objects.filter(username=username).first()
            if not user:
                raise CommandError(f"User not found: {username}")
            return user
        return User.objects.filter(is_superuser=True).first() or User.objects.first()
