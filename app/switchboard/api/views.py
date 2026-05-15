# switchboard/api/views.py

import logging

from django.conf import settings
from django.http import JsonResponse
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


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def classify_async_proxy(request):
    text = (request.data.get("text") or "").strip()
    max_tags = int(request.data.get("max_tags") or 8)

    if not text:
        return JsonResponse({"detail": "text is required."}, status=400)
    if len(text) < 30:
        return JsonResponse({"detail": "text too short to classify (minimum 30 characters)"}, status=400)

    tenant_id = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", _DEFAULT_TENANT_ID))
    tenant_namespace = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", _DEFAULT_TENANT_NAMESPACE))

    action_run = ActionRun.objects.create(
        tool_name="inkwell.classify",
        status=ActionRunStatus.PENDING,
        execution_mode=ActionRunExecutionMode.LOCAL,
        tenant_id=tenant_id,
        tenant_namespace=tenant_namespace,
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id=str(request.user.pk),
        request_payload={"text_length": len(text), "max_tags": max_tags},
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


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def summarize_async_proxy(request):
    if not request.user.is_superuser:
        return JsonResponse({"detail": "Superuser access required."}, status=403)

    text = (request.data.get("text") or "").strip()
    words = int(request.data.get("words") or 40)
    style = (request.data.get("style") or "neutral").strip()

    if not text:
        return JsonResponse({"detail": "text is required."}, status=400)

    tenant_id = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", _DEFAULT_TENANT_ID))
    tenant_namespace = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", _DEFAULT_TENANT_NAMESPACE))

    action_run = ActionRun.objects.create(
        tool_name="inkwell.summarize",
        status=ActionRunStatus.PENDING,
        execution_mode=ActionRunExecutionMode.LOCAL,
        tenant_id=tenant_id,
        tenant_namespace=tenant_namespace,
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id=str(request.user.pk),
        request_payload={"text_length": len(text), "words": words, "style": style},
    )

    summarize_payload = {"text": text, "words": words, "style": style}

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
        "Enqueued async summarize action_run=%s user=%s text_len=%s",
        action_run.id,
        request.user.pk,
        len(text),
    )

    return JsonResponse({"action_run_id": str(action_run.id)}, status=202)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def think_cluster_async_proxy(request):
    if not request.user.is_superuser:
        return JsonResponse({"detail": "Superuser access required."}, status=403)

    initiative_id_raw = (request.data.get("initiative_id") or "").strip()
    entries = request.data.get("entries") or []

    if not initiative_id_raw:
        return JsonResponse({"detail": "initiative_id is required."}, status=400)
    if not isinstance(entries, list):
        return JsonResponse({"detail": "entries must be a list."}, status=400)

    from initiatives.models import Initiative
    from django.shortcuts import get_object_or_404
    initiative = get_object_or_404(Initiative, pk=initiative_id_raw)

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
    note = create_note_from_agent(
        created_by=request.user,
        **serializer.validated_data,
    )
    return JsonResponse(NoteSerializer(note).data, status=201)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agent_reminder_proxy(request):
    if not request.user.is_superuser:
        return JsonResponse({"detail": "Superuser access required."}, status=403)

    serializer = AgentReminderCommandSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    reminder = create_reminder_from_agent(
        created_by=request.user,
        **serializer.validated_data,
    )
    return JsonResponse(ReminderSerializer(reminder).data, status=201)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agent_task_proxy(request):
    if not request.user.is_superuser:
        return JsonResponse({"detail": "Superuser access required."}, status=403)

    serializer = AgentTaskCommandSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    task = create_task_from_agent(
        created_by=request.user,
        **serializer.validated_data,
    )
    return JsonResponse(TaskSerializer(task).data, status=201)
