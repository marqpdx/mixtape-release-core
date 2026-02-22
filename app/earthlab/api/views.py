# earthlab/api/views.py

from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from earthlab.models import Course, Lesson, CourseItem, CourseRun, Enrollment, LessonProgress
from earthlab.choices import ProgressStatus
from groups.models import Group
from stackroom.models import Library


def _group_and_ct(group_slug):
    group = get_object_or_404(Group, slug=group_slug)
    ct = ContentType.objects.get_for_model(Group)
    return group, ct


def _serialize_course(c):
    return {
        'id': str(c.id),
        'title': c.title,
        'slug': c.slug,
        'summary': c.summary,
        'body': c.body,
        'status': c.status,
        'difficulty_level': c.difficulty_level,
        'delivery_type': c.delivery_type,
        'estimated_duration': c.estimated_duration,
        'learning_objectives': c.learning_objectives,
        'flow_mode': c.flow_mode,
        'created_at': c.created_at,
        'updated_at': c.updated_at,
    }


def _serialize_course_with_items(c):
    data = _serialize_course(c)
    items = CourseItem.objects.filter(course=c).order_by('position')
    data['items'] = []
    for item in items:
        obj = item.content_object
        data['items'].append({
            'id': str(item.id),
            'position': item.position,
            'section_title': item.section_title,
            'content_type': item.content_type.model,
            'content_id': str(item.content_object_id),
            'content_title': getattr(obj, 'title', '') if obj else '',
            'content_slug': getattr(obj, 'slug', '') if obj else '',
            'estimated_duration': getattr(obj, 'estimated_duration', None) if obj else None,
        })
    return data


def _serialize_lesson(l):
    return {
        'id': str(l.id),
        'title': l.title,
        'slug': l.slug,
        'summary': l.summary,
        'body': l.body,
        'status': l.status,
        'difficulty_level': l.difficulty_level,
        'estimated_duration': l.estimated_duration,
        'tiptap_json': l.tiptap_json,
        'created_at': l.created_at,
        'updated_at': l.updated_at,
    }


# ============================================================================
# Course endpoints
# ============================================================================

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def list_or_create_courses(request, group_slug):
    """
    GET  /api/earthlab/{group_slug}/courses — list courses
    POST /api/earthlab/{group_slug}/courses — create course
    """
    group, ct = _group_and_ct(group_slug)

    if request.method == 'GET':
        courses = Course.objects.filter(
            sponsor_content_type=ct,
            sponsor_object_id=group.id,
            deleted_at__isnull=True,
        ).order_by('-updated_at')
        return Response([_serialize_course(c) for c in courses])

    # POST — create
    with transaction.atomic():
        course = Course(
            title=request.data.get('title', ''),
            summary=request.data.get('summary', ''),
            body=request.data.get('body', ''),
            status=request.data.get('status', 'draft'),
            difficulty_level=request.data.get('difficulty_level', ''),
            delivery_type=request.data.get('delivery_type', 'self_paced'),
            estimated_duration=request.data.get('estimated_duration'),
            learning_objectives=request.data.get('learning_objectives', []),
            author=request.user,
            submitted_by=request.user,
        )
        course.set_sponsor(group)
        course.save()

    # Fire activity producer
    try:
        from earthlab.producers import on_earthlab_course_updated
        on_earthlab_course_updated(course=course, group=group, actor_user=request.user)
    except Exception:
        pass

    return Response(_serialize_course(course), status=201)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def course_detail(request, group_slug, course_slug):
    """
    GET    /api/earthlab/{group_slug}/courses/{course_slug}
    PATCH  /api/earthlab/{group_slug}/courses/{course_slug}
    DELETE /api/earthlab/{group_slug}/courses/{course_slug}
    """
    group, ct = _group_and_ct(group_slug)
    course = get_object_or_404(
        Course,
        slug=course_slug,
        sponsor_content_type=ct,
        sponsor_object_id=group.id,
        deleted_at__isnull=True,
    )

    if request.method == 'GET':
        return Response(_serialize_course_with_items(course))

    if request.method == 'PATCH':
        allowed = [
            'title', 'summary', 'body', 'status', 'difficulty_level',
            'delivery_type', 'estimated_duration', 'learning_objectives',
        ]
        with transaction.atomic():
            for field in allowed:
                if field in request.data:
                    setattr(course, field, request.data[field])
            course.save()

        # Fire activity producer
        try:
            from earthlab.producers import on_earthlab_course_updated
            on_earthlab_course_updated(course=course, group=group, actor_user=request.user)
        except Exception:
            pass

        return Response(_serialize_course_with_items(course))

    # DELETE — soft delete
    course.deleted_at = timezone.now()
    course.save(update_fields=['deleted_at'])
    return Response(status=204)


# ============================================================================
# Lesson endpoints
# ============================================================================

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def list_or_create_lessons(request, group_slug):
    """
    GET  /api/earthlab/{group_slug}/lessons — list lessons
    POST /api/earthlab/{group_slug}/lessons — create lesson
    """
    group, ct = _group_and_ct(group_slug)

    if request.method == 'GET':
        lessons = Lesson.objects.filter(
            sponsor_content_type=ct,
            sponsor_object_id=group.id,
            deleted_at__isnull=True,
        ).order_by('-updated_at')
        return Response([_serialize_lesson(l) for l in lessons])

    # POST — create
    with transaction.atomic():
        lesson = Lesson(
            title=request.data.get('title', ''),
            summary=request.data.get('summary', ''),
            body=request.data.get('body', ''),
            status=request.data.get('status', 'draft'),
            difficulty_level=request.data.get('difficulty_level', ''),
            estimated_duration=request.data.get('estimated_duration'),
            tiptap_json=request.data.get('tiptap_json'),
            author=request.user,
            submitted_by=request.user,
        )
        lesson.set_sponsor(group)
        lesson.save()

    # Fire activity producer (reuse course_updated — any earthlab change counts)
    try:
        from earthlab.producers import on_earthlab_course_updated
        on_earthlab_course_updated(course=lesson, group=group, actor_user=request.user)
    except Exception:
        pass

    return Response(_serialize_lesson(lesson), status=201)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def lesson_detail(request, group_slug, lesson_slug):
    """
    GET    /api/earthlab/{group_slug}/lessons/{lesson_slug}
    PATCH  /api/earthlab/{group_slug}/lessons/{lesson_slug}
    DELETE /api/earthlab/{group_slug}/lessons/{lesson_slug}
    """
    group, ct = _group_and_ct(group_slug)
    lesson = get_object_or_404(
        Lesson,
        slug=lesson_slug,
        sponsor_content_type=ct,
        sponsor_object_id=group.id,
        deleted_at__isnull=True,
    )

    if request.method == 'GET':
        return Response(_serialize_lesson(lesson))

    if request.method == 'PATCH':
        allowed = [
            'title', 'summary', 'body', 'status', 'difficulty_level',
            'estimated_duration', 'tiptap_json',
        ]
        with transaction.atomic():
            for field in allowed:
                if field in request.data:
                    setattr(lesson, field, request.data[field])
            lesson.save()
        return Response(_serialize_lesson(lesson))

    # DELETE — soft delete
    lesson.deleted_at = timezone.now()
    lesson.save(update_fields=['deleted_at'])
    return Response(status=204)


# ============================================================================
# Course Items (Outline)
# ============================================================================

CONTENT_TYPE_MAP = {
    'lesson': Lesson,
    'library': Library,
}


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_course_item(request, group_slug, course_slug):
    """POST /api/earthlab/{group_slug}/courses/{course_slug}/items"""
    group, ct = _group_and_ct(group_slug)
    course = get_object_or_404(
        Course, slug=course_slug,
        sponsor_content_type=ct, sponsor_object_id=group.id,
        deleted_at__isnull=True,
    )

    content_type_label = request.data.get('content_type', '')
    content_id = request.data.get('content_id', '')
    model_class = CONTENT_TYPE_MAP.get(content_type_label)
    if not model_class:
        return Response({'error': 'Invalid content_type'}, status=400)

    content_obj = get_object_or_404(model_class, id=content_id, deleted_at__isnull=True)
    content_ct = ContentType.objects.get_for_model(model_class)

    with transaction.atomic():
        max_pos = CourseItem.objects.filter(course=course).aggregate(
            m=models.Max('position'))['m'] or 0
        item = CourseItem.objects.create(
            course=course,
            content_type=content_ct,
            content_object_id=content_obj.id,
            position=max_pos + 1,
            section_title=request.data.get('section_title', ''),
        )

    return Response({
        'id': str(item.id),
        'position': item.position,
        'section_title': item.section_title,
        'content_type': content_ct.model,
        'content_id': str(content_obj.id),
        'content_title': getattr(content_obj, 'title', ''),
        'content_slug': getattr(content_obj, 'slug', ''),
        'estimated_duration': getattr(content_obj, 'estimated_duration', None),
    }, status=201)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def remove_course_item(request, group_slug, course_slug, item_id):
    """DELETE /api/earthlab/{group_slug}/courses/{course_slug}/items/{item_id}"""
    group, ct = _group_and_ct(group_slug)
    course = get_object_or_404(
        Course, slug=course_slug,
        sponsor_content_type=ct, sponsor_object_id=group.id,
        deleted_at__isnull=True,
    )
    item = get_object_or_404(CourseItem, id=item_id, course=course)
    item.delete()
    return Response(status=204)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reorder_course_items(request, group_slug, course_slug):
    """POST /api/earthlab/{group_slug}/courses/{course_slug}/items/reorder"""
    group, ct = _group_and_ct(group_slug)
    course = get_object_or_404(
        Course, slug=course_slug,
        sponsor_content_type=ct, sponsor_object_id=group.id,
        deleted_at__isnull=True,
    )

    items_data = request.data.get('items', [])
    if not items_data:
        return Response({'error': 'items required'}, status=400)

    with transaction.atomic():
        # Clear positions first to avoid unique constraint violations
        CourseItem.objects.filter(course=course).update(position=0)
        for entry in items_data:
            CourseItem.objects.filter(
                id=entry['id'], course=course,
            ).update(position=entry['position'])

    return Response(status=204)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_available_content(request, group_slug):
    """GET /api/earthlab/{group_slug}/available-content"""
    group, ct = _group_and_ct(group_slug)

    lessons = Lesson.objects.filter(
        sponsor_content_type=ct, sponsor_object_id=group.id,
        deleted_at__isnull=True,
    ).order_by('title')

    libraries = Library.objects.filter(
        sponsor_content_type=ct, sponsor_object_id=group.id,
        deleted_at__isnull=True,
    ).order_by('title')

    return Response({
        'lessons': [
            {'id': str(l.id), 'title': l.title, 'slug': l.slug}
            for l in lessons
        ],
        'libraries': [
            {'id': str(lib.id), 'title': lib.title, 'slug': lib.slug,
             'scope': getattr(lib, 'scope', '')}
            for lib in libraries
        ],
    })


# ============================================================================
# Course Runs
# ============================================================================

def _serialize_run(run):
    return {
        'id': str(run.id),
        'title': run.title,
        'status': run.status,
        'enrollment_policy': run.enrollment_policy,
        'start_date': run.start_date,
        'end_date': run.end_date,
        'max_enrollment': run.max_enrollment,
        'enrollment_count': run.enrollments.filter(
            status__in=['enrolled', 'completed'],
        ).count(),
        'created_at': run.created_at,
    }


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def list_or_create_runs(request, group_slug, course_slug):
    """
    GET  /api/earthlab/{group_slug}/courses/{course_slug}/runs
    POST /api/earthlab/{group_slug}/courses/{course_slug}/runs
    """
    group, ct = _group_and_ct(group_slug)
    course = get_object_or_404(
        Course, slug=course_slug,
        sponsor_content_type=ct, sponsor_object_id=group.id,
        deleted_at__isnull=True,
    )

    if request.method == 'GET':
        runs = CourseRun.objects.filter(
            course=course, deleted_at__isnull=True,
        ).order_by('-start_date', '-created_at')
        return Response([_serialize_run(r) for r in runs])

    # POST
    with transaction.atomic():
        run = CourseRun.objects.create(
            course=course,
            title=request.data.get('title', ''),
            status=request.data.get('status', 'upcoming'),
            enrollment_policy=request.data.get('enrollment_policy', 'open'),
            start_date=request.data.get('start_date'),
            end_date=request.data.get('end_date'),
            max_enrollment=request.data.get('max_enrollment'),
        )
    return Response(_serialize_run(run), status=201)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def run_detail(request, group_slug, course_slug, run_id):
    """
    PATCH  /api/earthlab/{group_slug}/courses/{course_slug}/runs/{run_id}
    DELETE /api/earthlab/{group_slug}/courses/{course_slug}/runs/{run_id}
    """
    group, ct = _group_and_ct(group_slug)
    course = get_object_or_404(
        Course, slug=course_slug,
        sponsor_content_type=ct, sponsor_object_id=group.id,
        deleted_at__isnull=True,
    )
    run = get_object_or_404(CourseRun, id=run_id, course=course, deleted_at__isnull=True)

    if request.method == 'PATCH':
        allowed = ['title', 'status', 'enrollment_policy', 'start_date', 'end_date', 'max_enrollment']
        with transaction.atomic():
            for field in allowed:
                if field in request.data:
                    setattr(run, field, request.data[field])
            run.save()
        return Response(_serialize_run(run))

    # DELETE
    run.deleted_at = timezone.now()
    run.save(update_fields=['deleted_at'])
    return Response(status=204)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def enroll_in_run(request, group_slug, course_slug, run_id):
    """POST /api/earthlab/{group_slug}/courses/{course_slug}/runs/{run_id}/enroll"""
    group, ct = _group_and_ct(group_slug)
    course = get_object_or_404(
        Course, slug=course_slug,
        sponsor_content_type=ct, sponsor_object_id=group.id,
        deleted_at__isnull=True,
    )
    run = get_object_or_404(CourseRun, id=run_id, course=course, deleted_at__isnull=True)

    if run.enrollment_policy == 'closed':
        return Response({'error': 'Enrollment is closed'}, status=400)

    if run.max_enrollment:
        current = run.enrollments.filter(status__in=['enrolled', 'completed']).count()
        if current >= run.max_enrollment:
            return Response({'error': 'Course run is full'}, status=400)

    enrollment, created = Enrollment.objects.get_or_create(
        course_run=run,
        user=request.user,
        defaults={'status': 'enrolled'},
    )

    if not created and enrollment.status == 'dropped':
        enrollment.status = 'enrolled'
        enrollment.save(update_fields=['status'])

    return Response({
        'id': str(enrollment.id),
        'status': enrollment.status,
        'enrolled_at': enrollment.enrolled_at,
    }, status=201 if created else 200)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_progress(request, group_slug, course_slug, run_id):
    """GET /api/earthlab/{group_slug}/courses/{course_slug}/runs/{run_id}/progress"""
    group, ct = _group_and_ct(group_slug)
    course = get_object_or_404(
        Course, slug=course_slug,
        sponsor_content_type=ct, sponsor_object_id=group.id,
        deleted_at__isnull=True,
    )
    run = get_object_or_404(CourseRun, id=run_id, course=course, deleted_at__isnull=True)
    enrollment = get_object_or_404(Enrollment, course_run=run, user=request.user)

    lesson_progress = LessonProgress.objects.filter(enrollment=enrollment)
    total_items = CourseItem.objects.filter(course=course).count()
    completed_lessons = lesson_progress.filter(status=ProgressStatus.COMPLETED).count()

    return Response({
        'enrollment_id': str(enrollment.id),
        'enrollment_status': enrollment.status,
        'total_items': total_items,
        'completed_lessons': completed_lessons,
        'lessons': [
            {
                'id': str(lp.id),
                'lesson_content_type': lp.lesson_content_type.model,
                'lesson_object_id': str(lp.lesson_object_id),
                'status': lp.status,
                'started_at': lp.started_at,
                'completed_at': lp.completed_at,
            }
            for lp in lesson_progress
        ],
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_lesson_complete(request, group_slug, course_slug, run_id):
    """POST /api/earthlab/{group_slug}/courses/{course_slug}/runs/{run_id}/mark-complete"""
    group, ct = _group_and_ct(group_slug)
    course = get_object_or_404(
        Course, slug=course_slug,
        sponsor_content_type=ct, sponsor_object_id=group.id,
        deleted_at__isnull=True,
    )
    run = get_object_or_404(CourseRun, id=run_id, course=course, deleted_at__isnull=True)
    enrollment = get_object_or_404(Enrollment, course_run=run, user=request.user)

    content_type_label = request.data.get('content_type', 'lesson')
    content_id = request.data.get('content_id', '')

    model_class = CONTENT_TYPE_MAP.get(content_type_label)
    if not model_class:
        return Response({'error': 'Invalid content_type'}, status=400)

    content_ct = ContentType.objects.get_for_model(model_class)

    progress, created = LessonProgress.objects.get_or_create(
        enrollment=enrollment,
        lesson_content_type=content_ct,
        lesson_object_id=content_id,
        defaults={
            'status': ProgressStatus.COMPLETED,
            'started_at': timezone.now(),
            'completed_at': timezone.now(),
        },
    )

    if not created and progress.status != ProgressStatus.COMPLETED:
        progress.status = ProgressStatus.COMPLETED
        progress.completed_at = timezone.now()
        progress.save(update_fields=['status', 'completed_at'])

    return Response({
        'id': str(progress.id),
        'status': progress.status,
        'completed_at': progress.completed_at,
    })
