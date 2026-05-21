# switchboard/api/views.py

import logging

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from initiatives.api.serializers import NoteSerializer, ReminderSerializer, TaskSerializer
from initiatives.services import (
    AgentParseError,
    create_note_from_agent,
    parse_agent_command,
    create_reminder_from_agent,
    create_task_from_agent,
)
from initiatives.models import (
    ActionRun,
    ActionRunExecutionMode,
    ActionRunInitiatorType,
    ActionRunStatus,
)
from mixtape.celery_app import app as celery_app
from switchboard.api.serializers import (
    AgentNoteCommandSerializer,
    AgentParseRequestSerializer,
    AgentReminderCommandSerializer,
    AgentTaskCommandSerializer,
)

logger = logging.getLogger(__name__)

_DEFAULT_TENANT_ID = getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", "00000000-0000-0000-0000-000000000001")
_DEFAULT_TENANT_NAMESPACE = getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", "platform:crossroads")


_VALID_SURFACES = {"console", "puddlejump"}


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def classify_async_proxy(request):
    text = (request.data.get("text") or "").strip()
    max_tags = int(request.data.get("max_tags") or 8)
    surface = (request.data.get("surface") or "console").strip()
    if surface not in _VALID_SURFACES:
        surface = "console"

    if not text:
        return JsonResponse({"detail": "text is required."}, status=400)
    if len(text) < 30:
        return JsonResponse({"detail": "text too short to classify (minimum 30 characters)"}, status=400)

    tenant_id = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", _DEFAULT_TENANT_ID))
    tenant_namespace = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", _DEFAULT_TENANT_NAMESPACE))

    action_run = ActionRun.objects.create(
        tool_name=f"{surface}.classify",
        status=ActionRunStatus.PENDING,
        execution_mode=ActionRunExecutionMode.LOCAL,
        tenant_id=tenant_id,
        tenant_namespace=tenant_namespace,
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id=str(request.user.pk),
        request_payload={"text_length": len(text), "max_tags": max_tags, "surface": surface},
    )

    classify_payload = {"text": text, "max_tags": max_tags}

    celery_app.send_task(
        "switchboard.classify_async",
        kwargs={
            "action_run_id": str(action_run.id),
            "tenant_id": tenant_id,
            "tenant_namespace": tenant_namespace,
            "principal_user_id": str(request.user.pk),
            "principal_service_token_id": None,
            "request_payload": classify_payload,
            "classify_payload": classify_payload,
        },
        queue="switchboard",
    )

    logger.info(
        "Enqueued async classify action_run=%s user=%s text_len=%s",
        action_run.id,
        request.user.pk,
        len(text),
    )

    return JsonResponse({"action_run_id": str(action_run.id)}, status=202)


_VALID_CONTENT_TYPES = {"writing.piece", "puddlejump.item", "puddlejump.snapshot"}
_VALID_SUMMARY_STYLES = {"brief", "standard", "extended"}


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def summarize_async_proxy(request):
    text = (request.data.get("text") or "").strip()
    content_type = (request.data.get("content_type") or "").strip()
    surface = (request.data.get("surface") or "console").strip()
    if surface not in _VALID_SURFACES:
        surface = "console"
    words = int(request.data.get("words") or 40)
    style = (request.data.get("style") or "neutral").strip()
    summary_style = (request.data.get("summary_style") or "standard").strip()
    if summary_style not in _VALID_SUMMARY_STYLES:
        summary_style = "standard"
    source_id = (request.data.get("source_id") or "").strip() or None

    if not text:
        return JsonResponse({"detail": "text is required."}, status=400)
    if not content_type:
        return JsonResponse({"detail": "content_type is required (writing.piece | puddlejump.item | puddlejump.snapshot)."}, status=400)
    if content_type not in _VALID_CONTENT_TYPES:
        return JsonResponse({"detail": f"content_type must be one of: {', '.join(sorted(_VALID_CONTENT_TYPES))}"}, status=400)

    tenant_id = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", _DEFAULT_TENANT_ID))
    tenant_namespace = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", _DEFAULT_TENANT_NAMESPACE))

    action_run = ActionRun.objects.create(
        tool_name=f"{surface}.summarize",
        status=ActionRunStatus.PENDING,
        execution_mode=ActionRunExecutionMode.LOCAL,
        tenant_id=tenant_id,
        tenant_namespace=tenant_namespace,
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id=str(request.user.pk),
        request_payload={
            "text_length": len(text),
            "content_type": content_type,
            "surface": surface,
            "words": words,
            "style": style,
            "summary_style": summary_style,
            "source_id": source_id,
        },
    )

    summarize_payload = {
        "text": text,
        "content_type": content_type,
        "words": words,
        "style": style,
        "summary_style": summary_style,
        "source_id": source_id,
    }

    celery_app.send_task(
        "switchboard.summarize_async",
        kwargs={
            "action_run_id": str(action_run.id),
            "tenant_id": tenant_id,
            "tenant_namespace": tenant_namespace,
            "principal_user_id": str(request.user.pk),
            "principal_service_token_id": None,
            "request_payload": summarize_payload,
            "summarize_payload": summarize_payload,
        },
        queue="switchboard",
    )

    logger.info(
        "Enqueued async summarize action_run=%s user=%s content_type=%s text_len=%s",
        action_run.id,
        request.user.pk,
        content_type,
        len(text),
    )

    return JsonResponse({"action_run_id": str(action_run.id)}, status=202)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def context_shape_async_proxy(request):
    text = (request.data.get("text") or "").strip()
    surface = (request.data.get("surface") or "console").strip()
    if surface not in _VALID_SURFACES:
        surface = "console"
    group_context = (request.data.get("group_context") or "").strip() or None

    if not text:
        return JsonResponse({"detail": "text is required."}, status=400)

    tenant_id = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", _DEFAULT_TENANT_ID))
    tenant_namespace = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", _DEFAULT_TENANT_NAMESPACE))

    action_run = ActionRun.objects.create(
        tool_name=f"{surface}.context_shape",
        status=ActionRunStatus.PENDING,
        execution_mode=ActionRunExecutionMode.LOCAL,
        tenant_id=tenant_id,
        tenant_namespace=tenant_namespace,
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id=str(request.user.pk),
        request_payload={
            "text_length": len(text),
            "surface": surface,
            "has_group_context": bool(group_context),
        },
    )

    shape_payload = {"text": text, "group_context": group_context}

    celery_app.send_task(
        "switchboard.context_shape_async",
        kwargs={
            "action_run_id": str(action_run.id),
            "tenant_id": tenant_id,
            "tenant_namespace": tenant_namespace,
            "principal_user_id": str(request.user.pk),
            "principal_service_token_id": None,
            "request_payload": shape_payload,
            "shape_payload": shape_payload,
        },
        queue="switchboard",
    )

    logger.info(
        "Enqueued context_shape action_run=%s user=%s text_len=%s surface=%s",
        action_run.id,
        request.user.pk,
        len(text),
        surface,
    )

    return JsonResponse({"action_run_id": str(action_run.id)}, status=202)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def think_cluster_async_proxy(request):
    if not request.user.is_superuser:
        return JsonResponse({"detail": "Superuser access required."}, status=403)

    initiative_id_raw = (request.data.get("initiative_id") or "").strip()

    if not initiative_id_raw:
        return JsonResponse({"detail": "initiative_id is required."}, status=400)

    from initiatives.models import ApertureLog, ApertureLogEntry, ApertureLogEntryKind, Initiative
    from django.shortcuts import get_object_or_404
    initiative = get_object_or_404(Initiative, pk=initiative_id_raw)

    # Collect content entries from the current run window (since last RUN_BOUNDARY).
    try:
        aperture_log = ApertureLog.objects.get(initiative=initiative)
    except ApertureLog.DoesNotExist:
        return JsonResponse({"detail": "Initiative has no ApertureLog — add entries first."}, status=422)

    last_boundary = (
        ApertureLogEntry.objects
        .filter(aperture_log=aperture_log, kind=ApertureLogEntryKind.RUN_BOUNDARY)
        .order_by("-created_at")
        .first()
    )
    qs = ApertureLogEntry.objects.filter(
        aperture_log=aperture_log,
        kind__in=[ApertureLogEntryKind.PROSE, ApertureLogEntryKind.EMPH],
        archived_at__isnull=True,
    ).order_by("created_at")
    if last_boundary:
        qs = qs.filter(created_at__gt=last_boundary.created_at)

    entries = []
    for entry in qs:
        text = entry.emph_note if entry.kind == ApertureLogEntryKind.EMPH else entry.body
        if text and text.strip():
            entries.append(text.strip())

    if not entries:
        return JsonResponse(
            {"detail": "No content entries in the current run window. Add prose or /emph entries, then run /run before clustering."},
            status=422,
        )

    tenant_id = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", _DEFAULT_TENANT_ID))
    tenant_namespace = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", _DEFAULT_TENANT_NAMESPACE))

    action_run = ActionRun.objects.create(
        tool_name="think.cluster",
        status=ActionRunStatus.PENDING,
        execution_mode=ActionRunExecutionMode.LOCAL,
        initiative=initiative,
        tenant_id=tenant_id,
        tenant_namespace=tenant_namespace,
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id=str(request.user.pk),
        request_payload={"initiative_id": initiative_id_raw, "entry_count": len(entries)},
    )

    celery_app.send_task(
        "switchboard.think_cluster_async",
        kwargs={
            "action_run_id": str(action_run.id),
            "tenant_id": tenant_id,
            "tenant_namespace": tenant_namespace,
            "principal_user_id": str(request.user.pk),
            "principal_service_token_id": None,
            "initiative_id": initiative_id_raw,
            "entries": entries,
        },
        queue="switchboard",
        exchange="switchboard",
        routing_key="switchboard",
    )

    logger.info(
        "Enqueued think.cluster action_run=%s initiative=%s user=%s entries=%d",
        action_run.id,
        initiative_id_raw,
        request.user.pk,
        len(entries),
    )

    return JsonResponse({"action_run_id": str(action_run.id), "initiative_id": initiative_id_raw}, status=202)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agent_parse_proxy(request):
    if not request.user.is_superuser:
        return JsonResponse({"detail": "Superuser access required."}, status=403)

    serializer = AgentParseRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    payload = dict(serializer.validated_data)
    context = payload.pop("context", {}) or {}
    try:
        result = parse_agent_command(
            text=payload["text"],
            capture_mode=payload["capture_mode"],
            source=payload["source"],
            initiative_id=payload.get("initiative_id"),
            sponsor_model=context.get("sponsor_model"),
            sponsor_id=context.get("sponsor_id"),
            principal_user_id=request.user.pk,
        )
    except AgentParseError as exc:
        logger.error("Inkwell /service/agent/parse error %s: %s", exc.status_code, exc.body[:500])
        http_status = (
            status.HTTP_504_GATEWAY_TIMEOUT
            if exc.status_code == 504
            else status.HTTP_502_BAD_GATEWAY
        )
        return JsonResponse(
            {"detail": exc.detail, "status_code": exc.status_code, "body": exc.body},
            status=http_status,
        )

    return JsonResponse(result, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agent_note_proxy(request):
    if not request.user.is_superuser:
        return JsonResponse({"detail": "Superuser access required."}, status=403)

    serializer = AgentNoteCommandSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    action_run = ActionRun.objects.create(
        tool_name="agent.note",
        status=ActionRunStatus.RUNNING,
        execution_mode=ActionRunExecutionMode.LOCAL,
        tenant_id=_DEFAULT_TENANT_ID,
        tenant_namespace=_DEFAULT_TENANT_NAMESPACE,
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id=str(request.user.pk),
        request_payload=serializer.validated_data,
        started_at=timezone.now(),
    )
    try:
        note = create_note_from_agent(created_by=request.user, **serializer.validated_data)
        action_run.status = ActionRunStatus.SUCCEEDED
        action_run.result_payload = {"object_id": str(note.id), "object_type": "note"}
        action_run.completed_at = timezone.now()
        action_run.save(update_fields=["status", "result_payload", "completed_at", "updated_at"])
        data = NoteSerializer(note).data
        data["action_run_id"] = str(action_run.id)
        return JsonResponse(data, status=201)
    except Exception as exc:
        action_run.status = ActionRunStatus.FAILED
        action_run.error_payload = {"error": str(exc)}
        action_run.completed_at = timezone.now()
        action_run.save(update_fields=["status", "error_payload", "completed_at", "updated_at"])
        raise


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agent_reminder_proxy(request):
    if not request.user.is_superuser:
        return JsonResponse({"detail": "Superuser access required."}, status=403)

    serializer = AgentReminderCommandSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    action_run = ActionRun.objects.create(
        tool_name="agent.remind",
        status=ActionRunStatus.RUNNING,
        execution_mode=ActionRunExecutionMode.LOCAL,
        tenant_id=_DEFAULT_TENANT_ID,
        tenant_namespace=_DEFAULT_TENANT_NAMESPACE,
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id=str(request.user.pk),
        request_payload=serializer.validated_data,
        started_at=timezone.now(),
    )
    try:
        reminder = create_reminder_from_agent(created_by=request.user, **serializer.validated_data)
        action_run.status = ActionRunStatus.SUCCEEDED
        action_run.result_payload = {"object_id": str(reminder.id), "object_type": "reminder"}
        action_run.completed_at = timezone.now()
        action_run.save(update_fields=["status", "result_payload", "completed_at", "updated_at"])
        data = ReminderSerializer(reminder).data
        data["action_run_id"] = str(action_run.id)
        return JsonResponse(data, status=201)
    except Exception as exc:
        action_run.status = ActionRunStatus.FAILED
        action_run.error_payload = {"error": str(exc)}
        action_run.completed_at = timezone.now()
        action_run.save(update_fields=["status", "error_payload", "completed_at", "updated_at"])
        raise


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agent_task_proxy(request):
    if not request.user.is_superuser:
        return JsonResponse({"detail": "Superuser access required."}, status=403)

    serializer = AgentTaskCommandSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    action_run = ActionRun.objects.create(
        tool_name="agent.task",
        status=ActionRunStatus.RUNNING,
        execution_mode=ActionRunExecutionMode.LOCAL,
        tenant_id=_DEFAULT_TENANT_ID,
        tenant_namespace=_DEFAULT_TENANT_NAMESPACE,
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id=str(request.user.pk),
        request_payload=serializer.validated_data,
        started_at=timezone.now(),
    )
    try:
        task = create_task_from_agent(created_by=request.user, **serializer.validated_data)
        action_run.status = ActionRunStatus.SUCCEEDED
        action_run.result_payload = {"object_id": str(task.id), "object_type": "task"}
        action_run.completed_at = timezone.now()
        action_run.save(update_fields=["status", "result_payload", "completed_at", "updated_at"])
        data = TaskSerializer(task).data
        data["action_run_id"] = str(action_run.id)
        return JsonResponse(data, status=201)
    except Exception as exc:
        action_run.status = ActionRunStatus.FAILED
        action_run.error_payload = {"error": str(exc)}
        action_run.completed_at = timezone.now()
        action_run.save(update_fields=["status", "error_payload", "completed_at", "updated_at"])
        raise
