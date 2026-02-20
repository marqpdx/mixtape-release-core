# gristmill/api/views.py
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType

from gristmill.parser import parse_grist
from gristmill.models import MillDraft
from almanac.models import Event
from dateutil import parser as date_parser


@api_view(['POST'])
def parse_view(request):
    """
    Parse Grist without saving.
    POST /api/gristmill/parse/
    Body: {"grist": "..."}
    """
    grist = request.data.get('grist', '')
    result = parse_grist(grist)
    return Response(result)


@api_view(['POST'])
def save_draft_view(request):
    """
    Parse and save MillDraft.
    POST /api/gristmill/drafts/
    Body: {"grist": "..."}
    """
    grist = request.data.get('grist', '')
    result = parse_grist(grist)

    # Save first block only (multi-block is future)
    if not result['blocks']:
        return Response({'error': 'No blocks parsed'}, status=400)

    block = result['blocks'][0]

    draft = MillDraft.objects.create(
        created_by=request.user,
        grist_text=grist,
        ast_json=block,
        block_type=block['type'],
        status='staged'
    )

    return Response({
        'id': str(draft.id),
        'block_type': draft.block_type,
        'ast': block,
        'status': draft.status,
    })


@api_view(['GET'])
def list_drafts_view(request):
    """
    List user's MillDrafts.
    GET /api/gristmill/drafts/
    """
    drafts = MillDraft.objects.filter(created_by=request.user)

    return Response([{
        'id': str(d.id),
        'block_type': d.block_type,
        'ast': d.ast_json,
        'status': d.status,
        'created_at': d.created_at,
    } for d in drafts])


@api_view(['POST'])
def promote_draft_view(request, draft_id):
    """
    Promote MillDraft to domain object.
    POST /api/gristmill/drafts/{id}/promote/
    Body: {"group_slug": "optional-group-slug"}

    Sponsor resolution:
    - If group_slug provided: Use that Group as sponsor
    - Otherwise: Use request.user as sponsor
    """
    from groups.models import Group

    draft = MillDraft.objects.get(id=draft_id, created_by=request.user)

    if draft.status == 'promoted':
        return Response({'error': 'Already promoted'}, status=400)

    ast = draft.ast_json

    if ast['errors']:
        return Response({'errors': ast['errors']}, status=400)

    # Determine sponsor from request body
    group_slug = request.data.get('group_slug')
    timezone_name = request.data.get('timezone')
    if group_slug:
        try:
            sponsor = Group.objects.get(slug=group_slug)
        except Group.DoesNotExist:
            return Response({'error': f'Group not found: {group_slug}'}, status=404)
    else:
        sponsor = request.user

    # Promote based on type
    if ast['type'] == 'event':
        event = _promote_event(ast, request.user, sponsor, timezone_name=timezone_name)

        # Link
        draft.promoted_content_type = ContentType.objects.get_for_model(Event)
        draft.promoted_object_id = event.id
        draft.status = 'promoted'
        draft.promoted_at = timezone.now()
        draft.save()

        return Response({
            'draft_id': str(draft.id),
            'event_id': str(event.id),
            'event_slug': event.slug,
        })

    elif ast['type'] == 'course':
        from earthlab.models import Course
        course = _promote_course(ast, request.user, sponsor)

        draft.promoted_content_type = ContentType.objects.get_for_model(Course)
        draft.promoted_object_id = course.id
        draft.status = 'promoted'
        draft.promoted_at = timezone.now()
        draft.save()

        return Response({
            'draft_id': str(draft.id),
            'course_id': str(course.id),
            'course_slug': course.slug,
        })

    elif ast['type'] == 'lesson':
        from earthlab.models import Lesson
        lesson = _promote_lesson(ast, request.user, sponsor)

        draft.promoted_content_type = ContentType.objects.get_for_model(Lesson)
        draft.promoted_object_id = lesson.id
        draft.status = 'promoted'
        draft.promoted_at = timezone.now()
        draft.save()

        return Response({
            'draft_id': str(draft.id),
            'lesson_id': str(lesson.id),
            'lesson_slug': lesson.slug,
        })

    return Response({'error': 'Unknown block type'}, status=400)


def _promote_course(ast, user, sponsor):
    """
    Create Course from AST.
    Title comes from ast['title'] (from /course Title declaration).
    """
    from earthlab.models import Course

    fields = ast['fields']
    course = Course(
        title=ast['title'],
        status='draft',
        difficulty_level=fields.get('difficulty', ''),
        delivery_type=fields.get('delivery', 'self_paced'),
        estimated_duration=int(fields['duration']) if 'duration' in fields else None,
        body=fields.get('body', ''),
        author=user,
        submitted_by=user,
    )
    course.set_sponsor(sponsor)
    course.save()
    return course


def _promote_lesson(ast, user, sponsor):
    """
    Create Lesson from AST.
    Title comes from ast['title'] (from /lesson Title declaration).
    """
    from earthlab.models import Lesson

    fields = ast['fields']
    lesson = Lesson(
        title=ast['title'],
        status='draft',
        difficulty_level=fields.get('difficulty', ''),
        estimated_duration=int(fields['duration']) if 'duration' in fields else None,
        body=fields.get('body', ''),
        author=user,
        submitted_by=user,
    )
    lesson.set_sponsor(sponsor)
    lesson.save()
    return lesson


def _promote_event(ast, user, sponsor, timezone_name=None):
    """
    Create Event from AST.

    Args:
        ast: Parsed AST block
        user: User creating the event (author)
        sponsor: User or Group sponsoring the event

    Note: Title comes from ast['title'] (from /event Title declaration),
    all other fields come from ast['fields'] (key: value lines).
    """
    from datetime import timedelta

    fields = ast['fields']
    title = ast['title']  # From /event Title declaration

    # Parse datetime
    start_str = fields['start']
    start_time = date_parser.parse(start_str)
    if timezone.is_naive(start_time):
        tz = timezone.get_current_timezone()
        if timezone_name:
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(timezone_name)
            except Exception:
                tz = timezone.get_current_timezone()
        start_time = timezone.make_aware(start_time, tz)

    # Calculate end_time (default 60 minutes, or from duration field)
    duration_minutes = int(fields.get('duration', 60))
    end_time = start_time + timedelta(minutes=duration_minutes)

    # Use Event.objects.create_single_event (existing method)
    event = Event.objects.create_single_event(
        title=title,  # From block declaration
        start_time=start_time,  # Method expects start_time, not start
        end_time=end_time,  # Required parameter
        sponsor=sponsor,  # Group or User sponsor from context
        author=user,
        location=fields.get('location', ''),
        description=fields.get('body', ''),  # Method uses description, not body
        event_format=fields.get('format', 'workshop'),
        max_attendees=int(fields['max_attendees']) if 'max_attendees' in fields else None,
        registration_required=fields.get('registration_required', 'false').lower() == 'true',
        status='draft',  # Always create as draft
    )

    return event
