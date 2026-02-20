# earthlab/api/views.py

from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from earthlab.models import Course, Lesson
from groups.models import Group


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_courses(request, group_slug):
    """
    List courses for a group.
    GET /api/earthlab/{group_slug}/courses
    """
    group = get_object_or_404(Group, slug=group_slug)
    ct = ContentType.objects.get_for_model(Group)

    courses = Course.objects.filter(
        sponsor_content_type=ct,
        sponsor_object_id=group.id,
        deleted_at__isnull=True,
    ).order_by('-updated_at')

    return Response([{
        'id': str(c.id),
        'title': c.title,
        'slug': c.slug,
        'status': c.status,
        'difficulty_level': c.difficulty_level,
        'delivery_type': c.delivery_type,
        'estimated_duration': c.estimated_duration,
        'flow_mode': c.flow_mode,
        'created_at': c.created_at,
        'updated_at': c.updated_at,
    } for c in courses])


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_lessons(request, group_slug):
    """
    List lessons for a group.
    GET /api/earthlab/{group_slug}/lessons
    """
    group = get_object_or_404(Group, slug=group_slug)
    ct = ContentType.objects.get_for_model(Group)

    lessons = Lesson.objects.filter(
        sponsor_content_type=ct,
        sponsor_object_id=group.id,
        deleted_at__isnull=True,
    ).order_by('-updated_at')

    return Response([{
        'id': str(l.id),
        'title': l.title,
        'slug': l.slug,
        'status': l.status,
        'difficulty_level': l.difficulty_level,
        'estimated_duration': l.estimated_duration,
        'created_at': l.created_at,
        'updated_at': l.updated_at,
    } for l in lessons])
