# gristmill/api/views.py
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType

from gristmill.parser import parse_grist
from gristmill.models import MillDraft
from almanac.models import Event
from dateutil import parser as date_parser


def _with_first_block_warning(result):
    blocks = result.get('blocks') or []
    warning = None
    if len(blocks) > 1:
        warning = "Only the first block will be saved/promoted. Use full Grist Mill for multi-block input."
    return blocks, warning


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def parse_view(request):
    """
    Parse Grist without saving.
    POST /api/gristmill/parse/
    Body: {"grist": "..."}
    """
    grist = request.data.get('grist', '')
    result = parse_grist(grist)
    _, warning = _with_first_block_warning(result)
    if warning:
        result['warning'] = warning
    return Response(result)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def drafts_view(request):
    if request.method == 'GET':
        return list_drafts_view(request)
    return save_draft_view(request)


def save_draft_view(request):
    """
    Parse and save MillDraft.
    POST /api/gristmill/drafts/
    Body: {"grist": "..."}
    """
    grist = request.data.get('grist', '')
    result = parse_grist(grist)
    blocks, warning = _with_first_block_warning(result)

    # Save first block only (multi-block is future)
    if not blocks:
        return Response({'error': 'No blocks parsed'}, status=400)

    block = blocks[0]

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
        'warning': warning,
    })


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
@permission_classes([IsAuthenticated])
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

    try:
        draft = MillDraft.objects.get(id=draft_id, created_by=request.user)
    except MillDraft.DoesNotExist:
        return Response({'error': 'Draft not found'}, status=404)

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

    elif ast['type'] == 'issue':
        feedback_item = _promote_issue(ast, request.user, request.data.get('page_url', ''))

        from feedback.models import FeedbackItem
        draft.promoted_content_type = ContentType.objects.get_for_model(FeedbackItem)
        draft.promoted_object_id = feedback_item.id
        draft.status = 'promoted'
        draft.promoted_at = timezone.now()
        draft.save()

        return Response({
            'draft_id': str(draft.id),
            'feedback_item_id': str(feedback_item.id),
            'kind': feedback_item.kind,
        })

    elif ast['type'] == 'commons':
        commons_item = _promote_commons(ast, request.user, sponsor)

        from commons.models import CommonsItem
        draft.promoted_content_type = ContentType.objects.get_for_model(CommonsItem)
        draft.promoted_object_id = commons_item.id
        draft.status = 'promoted'
        draft.promoted_at = timezone.now()
        draft.save()

        return Response({
            'draft_id': str(draft.id),
            'commons_item_id': str(commons_item.id),
            'commons_item_slug': commons_item.slug,
        })

    return Response({'error': 'Unknown block type'}, status=400)


def _promote_commons(ast, user, sponsor):
    """
    Create CommonsItem from AST.
    Declaration line may be a URL or a title.
    """
    from commons import services as commons_service

    fields = ast['fields']
    declaration = ast['title']

    # If declaration looks like a URL, treat it as source_url
    source_url = ""
    title = declaration
    if declaration.startswith("http://") or declaration.startswith("https://"):
        source_url = declaration
        title = fields.get('title', declaration)

    # Also check explicit url field
    if fields.get('url'):
        source_url = fields['url']

    item = commons_service.capture_item(
        user=user,
        source_url=source_url,
        title=title,
        why_recommended=fields.get('why', ''),
        sponsor=sponsor,
    )

    # Apply optional fields
    if fields.get('location'):
        item.location_name = fields['location']
    if fields.get('type'):
        item.item_type = fields['type']
    if fields.get('body'):
        item.body = fields['body']

    if any(fields.get(k) for k in ('location', 'type', 'body')):
        item.save()

    # Trigger async extraction if a source URL was submitted.
    # Runs in the background — failure is silent, curator fills in manually.
    if item.source_url:
        try:
            from commons.tasks import extract_commons_item_task
            extract_commons_item_task.delay(str(item.id))
        except Exception:
            pass  # Celery unavailable — item is still captured, no data loss

    return item


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


def _promote_issue(ast, user, page_url=''):
    """
    Create FeedbackItem(kind=issue) from AST and attach to grist_issue_v1 beacon.
    """
    from feedback.models import FeedbackBeacon, FeedbackItem

    fields = ast.get('fields', {})
    lines = [ast.get('title', '').strip()]

    if fields.get('severity'):
        lines.append(f"Severity: {fields['severity']}")
    if fields.get('area'):
        lines.append(f"Area: {fields['area']}")
    if fields.get('steps'):
        lines.append(f"Steps:\n{fields['steps']}")
    if fields.get('expected'):
        lines.append(f"Expected:\n{fields['expected']}")
    if fields.get('actual'):
        lines.append(f"Actual:\n{fields['actual']}")
    if fields.get('body'):
        lines.append(f"Notes:\n{fields['body']}")

    message = "\n\n".join([line for line in lines if line])

    beacon, _ = FeedbackBeacon.objects.get_or_create(
        key="grist_issue_v1",
        defaults={
            "title": "Grist Issues",
            "body_markdown": "Issues created from Grist popup and Grist Mill.",
            "feature_context": "Use /issue for concise implementation-ready issue capture.",
            "is_active": True,
        },
    )
    if not beacon.is_active:
        beacon.is_active = True
        beacon.save(update_fields=["is_active"])

    return FeedbackItem.objects.create(
        beacon=beacon,
        kind=FeedbackItem.Kind.ISSUE,
        message=message,
        page_url=page_url or "",
        user=user,
    )
