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
    AgentAddCommandSerializer,
    AgentFindCommandSerializer,
    AgentNoteCommandSerializer,
    AgentParseRequestSerializer,
    AgentPatternCommandSerializer,
    AgentReminderCommandSerializer,
    AgentResearchCommandSerializer,
    AgentSynthesizeCommandSerializer,
    AgentSynthesizeNarrativeCommandSerializer,
    AgentSynopsisLinkedInCommandSerializer,
    AgentTaskCommandSerializer,
    GroupSearchSerializer,
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


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agent_add_proxy(request):
    serializer = AgentAddCommandSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    data = serializer.validated_data
    list_title = data["list_title"]
    new_items = data["items"]
    create_if_missing = data["create_if_missing"]

    from django.contrib.contenttypes.models import ContentType
    from lists.models import List as UserList
    from lists.api.serializers import ListSerializer as UserListSerializer

    user = request.user
    user_ct = ContentType.objects.get_for_model(user.__class__)

    action_run = ActionRun.objects.create(
        tool_name="agent.add",
        status=ActionRunStatus.RUNNING,
        execution_mode=ActionRunExecutionMode.LOCAL,
        tenant_id=_DEFAULT_TENANT_ID,
        tenant_namespace=_DEFAULT_TENANT_NAMESPACE,
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id=str(user.pk),
        request_payload={"list_title": list_title, "items": new_items},
        started_at=timezone.now(),
    )
    try:
        lst = UserList.objects.filter(
            sponsor_content_type=user_ct,
            sponsor_object_id=str(user.pk),
            title=list_title,
        ).first()

        if lst is None:
            if not create_if_missing:
                action_run.status = ActionRunStatus.FAILED
                action_run.error_payload = {"error": f"List '{list_title}' not found"}
                action_run.completed_at = timezone.now()
                action_run.save(update_fields=["status", "error_payload", "completed_at", "updated_at"])
                return JsonResponse(
                    {"detail": f"List '{list_title}' not found and create_if_missing is false."},
                    status=404,
                )
            lst = UserList.objects.create(
                title=list_title,
                body_text="",
                submitted_by=user,
                author=user,
                sponsor_content_type=user_ct,
                sponsor_object_id=str(user.pk),
            )

        appended_lines = "\n".join(f"- {item.strip()}" for item in new_items if item.strip())
        lst.body_text = (lst.body_text.rstrip("\n") + "\n" + appended_lines).lstrip("\n")
        lst.save(update_fields=["body_text", "updated_at"])

        action_run.status = ActionRunStatus.SUCCEEDED
        action_run.result_payload = {
            "object_id": str(lst.id),
            "object_type": "list",
            "items_added": len(new_items),
        }
        action_run.completed_at = timezone.now()
        action_run.save(update_fields=["status", "result_payload", "completed_at", "updated_at"])

        result = UserListSerializer(lst).data
        result["action_run_id"] = str(action_run.id)
        result["items_added"] = len(new_items)
        return JsonResponse(result, status=200)
    except Exception as exc:
        action_run.status = ActionRunStatus.FAILED
        action_run.error_payload = {"error": str(exc)}
        action_run.completed_at = timezone.now()
        action_run.save(update_fields=["status", "error_payload", "completed_at", "updated_at"])
        raise


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agent_find_proxy(request):
    serializer = AgentFindCommandSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    data = serializer.validated_data
    query = data["query"]
    library_id = data.get("library_id")
    limit = data["limit"]
    score_threshold = data["score_threshold"]
    surface = data.get("surface", "desktop")
    group_slug = (data.get("group_slug") or "").strip()

    from django.contrib.contenttypes.models import ContentType
    from initiatives.services.agent_stackroom import AgentStackroomError, retrieve_from_stackroom
    from puddlejump.models import Library

    user = request.user
    user_ct = ContentType.objects.get_for_model(user.__class__)

    # When surface=atrium, prepend keyword-matched List items before Codex results.
    list_hits: list[dict] = []
    if surface == "atrium":
        from lists.models import List as UserList
        from groups.models.group import Group

        if group_slug:
            group = Group.objects.filter(slug=group_slug, deleted_at__isnull=True).first()
            if group:
                sponsor_ct = ContentType.objects.get_for_model(Group)
                sponsor_id = str(group.pk)
            else:
                sponsor_ct, sponsor_id = user_ct, str(user.pk)
        else:
            sponsor_ct, sponsor_id = user_ct, str(user.pk)

        matching_lists = UserList.objects.filter(
            sponsor_content_type=sponsor_ct,
            sponsor_object_id=sponsor_id,
            body_text__icontains=query,
            deleted_at__isnull=True,
        )[:5]

        q_lower = query.lower()
        for lst in matching_lists:
            for line in lst.body_text.split("\n"):
                stripped = line.lstrip("- ").strip()
                if stripped and q_lower in stripped.lower():
                    list_hits.append({
                        "text": stripped,
                        "score": 1.0,
                        "artifact_type": "list",
                        "artifact_id": str(lst.id),
                        "source_file_id": "",
                        "list_title": lst.title,
                    })
                    if len(list_hits) >= 5:
                        break
            if len(list_hits) >= 5:
                break

    if library_id is None:
        try:
            lib = Library.objects.get(owner_content_type=user_ct, owner_object_id=user.id)
            library_id = lib.id
        except Library.DoesNotExist:
            if list_hits:
                # Return list-only results when no library exists yet
                return JsonResponse(
                    {
                        "results": list_hits,
                        "query": query,
                        "library_id": None,
                        "result_count": len(list_hits),
                        "action_run_id": "",
                    },
                    status=200,
                )
            return JsonResponse(
                {"detail": "No library found for this user. Upload files first."},
                status=404,
            )

    action_run = ActionRun.objects.create(
        tool_name="agent.find",
        status=ActionRunStatus.RUNNING,
        execution_mode=ActionRunExecutionMode.LOCAL,
        tenant_id=_DEFAULT_TENANT_ID,
        tenant_namespace=_DEFAULT_TENANT_NAMESPACE,
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id=str(user.pk),
        request_payload={"query": query, "library_id": str(library_id), "limit": limit},
        started_at=timezone.now(),
    )
    try:
        raw_results = retrieve_from_stackroom(
            query=query,
            library_id=library_id,
            limit=limit,
        )
        codex_results = [r for r in raw_results if r["score"] >= score_threshold]
        combined = list_hits + codex_results

        action_run.status = ActionRunStatus.SUCCEEDED
        action_run.result_payload = {
            "result_count": len(combined),
            "library_id": str(library_id),
            "query": query,
        }
        action_run.completed_at = timezone.now()
        action_run.save(update_fields=["status", "result_payload", "completed_at", "updated_at"])

        return JsonResponse(
            {
                "results": combined,
                "query": query,
                "library_id": str(library_id),
                "result_count": len(combined),
                "action_run_id": str(action_run.id),
            },
            status=200,
        )
    except AgentStackroomError as exc:
        action_run.status = ActionRunStatus.FAILED
        action_run.error_payload = {"error": str(exc), "status_code": exc.status_code}
        action_run.completed_at = timezone.now()
        action_run.save(update_fields=["status", "error_payload", "completed_at", "updated_at"])
        http_status = 504 if exc.status_code == 504 else 502
        return JsonResponse({"detail": exc.detail}, status=http_status)
    except Exception as exc:
        action_run.status = ActionRunStatus.FAILED
        action_run.error_payload = {"error": str(exc)}
        action_run.completed_at = timezone.now()
        action_run.save(update_fields=["status", "error_payload", "completed_at", "updated_at"])
        raise


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agent_research_proxy(request):
    serializer = AgentResearchCommandSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    data = serializer.validated_data
    query = data["query"]
    max_sources = data["max_sources"]
    surface = data["surface"]

    tenant_id = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", _DEFAULT_TENANT_ID))
    tenant_namespace = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", _DEFAULT_TENANT_NAMESPACE))

    research_payload = {"query": query, "max_sources": max_sources}

    action_run = ActionRun.objects.create(
        tool_name=f"{surface}.research",
        status=ActionRunStatus.PENDING,
        execution_mode=ActionRunExecutionMode.LOCAL,
        tenant_id=tenant_id,
        tenant_namespace=tenant_namespace,
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id=str(request.user.pk),
        request_payload={"query": query, "max_sources": max_sources, "surface": surface},
    )

    celery_app.send_task(
        "switchboard.research_async",
        kwargs={
            "action_run_id": str(action_run.id),
            "tenant_id": tenant_id,
            "tenant_namespace": tenant_namespace,
            "principal_user_id": str(request.user.pk),
            "principal_service_token_id": None,
            "request_payload": research_payload,
            "research_payload": research_payload,
        },
        queue="switchboard",
    )

    logger.info(
        "Enqueued research action_run=%s user=%s query_len=%d",
        action_run.id,
        request.user.pk,
        len(query),
    )

    return JsonResponse({"action_run_id": str(action_run.id)}, status=202)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agent_pattern_proxy(request):
    serializer = AgentPatternCommandSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    data = serializer.validated_data
    query = data["query"]
    library_id = data.get("library_id")
    max_sources = data["max_sources"]
    surface = data["surface"]

    from django.contrib.contenttypes.models import ContentType
    from initiatives.services.agent_stackroom import AgentStackroomError, retrieve_from_stackroom
    from puddlejump.models import Library

    user = request.user

    if library_id is None:
        user_ct = ContentType.objects.get_for_model(user.__class__)
        try:
            lib = Library.objects.get(owner_content_type=user_ct, owner_object_id=user.id)
            library_id = lib.id
        except Library.DoesNotExist:
            return JsonResponse(
                {"detail": "No library found for this user. Upload files first."},
                status=404,
            )

    # Fetch corpus here — Core owns the Stackroom integration; task receives pre-fetched items
    try:
        corpus_items = retrieve_from_stackroom(
            query=query,
            library_id=library_id,
            limit=max_sources,
        )
    except AgentStackroomError as exc:
        http_status = 504 if exc.status_code == 504 else 502
        return JsonResponse({"detail": exc.detail}, status=http_status)

    tenant_id = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", _DEFAULT_TENANT_ID))
    tenant_namespace = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", _DEFAULT_TENANT_NAMESPACE))

    pattern_payload = {"query": query, "library_id": str(library_id), "max_sources": max_sources}

    action_run = ActionRun.objects.create(
        tool_name=f"{surface}.pattern",
        status=ActionRunStatus.PENDING,
        execution_mode=ActionRunExecutionMode.LOCAL,
        tenant_id=tenant_id,
        tenant_namespace=tenant_namespace,
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id=str(user.pk),
        request_payload={
            "query": query,
            "library_id": str(library_id),
            "max_sources": max_sources,
            "surface": surface,
            "corpus_count": len(corpus_items),
        },
    )

    celery_app.send_task(
        "switchboard.pattern_async",
        kwargs={
            "action_run_id": str(action_run.id),
            "tenant_id": tenant_id,
            "tenant_namespace": tenant_namespace,
            "principal_user_id": str(user.pk),
            "principal_service_token_id": None,
            "request_payload": pattern_payload,
            "pattern_payload": pattern_payload,
            "corpus_items": corpus_items,
        },
        queue="switchboard",
    )

    logger.info(
        "Enqueued pattern action_run=%s user=%s query_len=%d corpus=%d",
        action_run.id,
        user.pk,
        len(query),
        len(corpus_items),
    )

    return JsonResponse({"action_run_id": str(action_run.id)}, status=202)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agent_synthesize_proxy(request):
    if not request.user.has_perm("initiatives.approve_cloud_dispatch"):
        return JsonResponse(
            {"detail": "You don't have permission to approve cloud AI dispatch."},
            status=403,
        )

    serializer = AgentSynthesizeCommandSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    data = serializer.validated_data
    query = data["query"]
    library_id = data.get("library_id")
    max_sources = data["max_sources"]
    surface = data["surface"]

    from django.contrib.contenttypes.models import ContentType
    from initiatives.services.agent_stackroom import AgentStackroomError, retrieve_from_stackroom
    from puddlejump.models import Library

    user = request.user

    if library_id is None:
        user_ct = ContentType.objects.get_for_model(user.__class__)
        try:
            lib = Library.objects.get(owner_content_type=user_ct, owner_object_id=user.id)
            library_id = lib.id
        except Library.DoesNotExist:
            return JsonResponse(
                {"detail": "No library found for this user. Upload files first."},
                status=404,
            )

    try:
        corpus_items = retrieve_from_stackroom(
            query=query,
            library_id=library_id,
            limit=max_sources,
        )
    except AgentStackroomError as exc:
        http_status = 504 if exc.status_code == 504 else 502
        return JsonResponse({"detail": exc.detail}, status=http_status)

    tenant_id = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", _DEFAULT_TENANT_ID))
    tenant_namespace = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", _DEFAULT_TENANT_NAMESPACE))

    synthesize_payload = {"query": query, "library_id": str(library_id), "max_sources": max_sources}

    action_run = ActionRun.objects.create(
        tool_name=f"{surface}.synthesize",
        status=ActionRunStatus.PENDING,
        execution_mode=ActionRunExecutionMode.CLOUD,
        tenant_id=tenant_id,
        tenant_namespace=tenant_namespace,
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id=str(user.pk),
        cloud_approved=True,
        request_payload={
            "query": query,
            "library_id": str(library_id),
            "max_sources": max_sources,
            "surface": surface,
            "corpus_count": len(corpus_items),
        },
    )

    celery_app.send_task(
        "switchboard.synthesize_async",
        kwargs={
            "action_run_id": str(action_run.id),
            "tenant_id": tenant_id,
            "tenant_namespace": tenant_namespace,
            "principal_user_id": str(user.pk),
            "principal_service_token_id": None,
            "request_payload": synthesize_payload,
            "synthesize_payload": synthesize_payload,
            "corpus_items": corpus_items,
        },
        queue="switchboard",
    )

    logger.info(
        "Enqueued synthesize action_run=%s user=%s query_len=%d corpus=%d",
        action_run.id,
        user.pk,
        len(query),
        len(corpus_items),
    )

    return JsonResponse({"action_run_id": str(action_run.id)}, status=202)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agent_synthesize_narrative_proxy(request):
    if not request.user.has_perm("initiatives.approve_cloud_dispatch"):
        return JsonResponse(
            {"detail": "You don't have permission to approve cloud AI dispatch."},
            status=403,
        )

    serializer = AgentSynthesizeNarrativeCommandSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    action_run_id = str(serializer.validated_data["action_run_id"])

    try:
        brief_run = ActionRun.objects.get(pk=action_run_id)
    except ActionRun.DoesNotExist:
        return JsonResponse({"detail": "Brief ActionRun not found."}, status=404)

    if brief_run.initiator_id != str(request.user.pk):
        return JsonResponse({"detail": "Not found."}, status=404)

    if brief_run.status != ActionRunStatus.SUCCEEDED:
        return JsonResponse(
            {"detail": "Brief run has not succeeded yet. Wait for it to complete before generating a narrative."},
            status=422,
        )

    if ".synthesize" not in (brief_run.tool_name or ""):
        return JsonResponse({"detail": "Referenced run is not a synthesize result."}, status=422)

    brief = brief_run.result_payload or {}
    narrative_payload = {
        "query": brief.get("query", ""),
        "key_points": brief.get("key_points", []),
        "tensions": brief.get("tensions", []),
        "synthesis_statement": brief.get("synthesis_statement", ""),
        "open_questions": brief.get("open_questions", []),
    }

    if not narrative_payload["query"]:
        return JsonResponse({"detail": "Brief run result is missing query field."}, status=422)

    tenant_id = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", _DEFAULT_TENANT_ID))
    tenant_namespace = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", _DEFAULT_TENANT_NAMESPACE))

    narrative_run = ActionRun.objects.create(
        tool_name=brief_run.tool_name.replace(".synthesize", ".synthesize_narrative"),
        status=ActionRunStatus.PENDING,
        execution_mode=ActionRunExecutionMode.CLOUD,
        tenant_id=tenant_id,
        tenant_namespace=tenant_namespace,
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id=str(request.user.pk),
        cloud_approved=True,
        parent_action=brief_run,
        request_payload={"brief_action_run_id": action_run_id, "query": narrative_payload["query"]},
    )

    celery_app.send_task(
        "switchboard.synthesize_narrative_async",
        kwargs={
            "action_run_id": str(narrative_run.id),
            "tenant_id": tenant_id,
            "tenant_namespace": tenant_namespace,
            "principal_user_id": str(request.user.pk),
            "principal_service_token_id": None,
            "request_payload": narrative_payload,
            "narrative_payload": narrative_payload,
        },
        queue="switchboard",
    )

    logger.info(
        "Enqueued synthesize_narrative action_run=%s brief_run=%s user=%s",
        narrative_run.id,
        action_run_id,
        request.user.pk,
    )

    return JsonResponse({"action_run_id": str(narrative_run.id)}, status=202)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agent_synopsis_linkedin_proxy(request):
    if not request.user.has_perm("initiatives.approve_cloud_dispatch"):
        return JsonResponse(
            {"detail": "You don't have permission to approve cloud AI dispatch."},
            status=403,
        )

    serializer = AgentSynopsisLinkedInCommandSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    piece_id = str(serializer.validated_data["piece_id"])
    surface = serializer.validated_data["surface"]

    from django.shortcuts import get_object_or_404
    from writing.models import WritingPiece
    from writing.synopsis_service import SynopsisGenerationService, _extract_plain_text

    user = request.user
    piece = get_object_or_404(WritingPiece, pk=piece_id)

    if piece.author != user and not user.is_staff:
        return JsonResponse({"detail": "Not found."}, status=404)

    synopsis = getattr(piece, "synopsis", None)
    if synopsis is None:
        synopsis = SynopsisGenerationService.generate_for_piece(piece)
    if synopsis is None:
        return JsonResponse(
            {"detail": "Could not initialise synopsis for this piece."},
            status=500,
        )

    title = piece.title or ""
    excerpt = piece.excerpt or ""
    body_preview = _extract_plain_text(piece.body_json or {}, char_limit=400)

    tenant_id = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", _DEFAULT_TENANT_ID))
    tenant_namespace = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", _DEFAULT_TENANT_NAMESPACE))

    synopsis_payload = {
        "title": title,
        "excerpt": excerpt,
        "body_preview": body_preview,
    }

    action_run = ActionRun.objects.create(
        tool_name="writing.synopsis_linkedin",
        status=ActionRunStatus.PENDING,
        execution_mode=ActionRunExecutionMode.CLOUD,
        tenant_id=tenant_id,
        tenant_namespace=tenant_namespace,
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id=str(user.pk),
        cloud_approved=True,
        request_payload={
            "piece_id": piece_id,
            "title": title,
            "surface": surface,
        },
    )

    celery_app.send_task(
        "switchboard.synopsis_linkedin_async",
        kwargs={
            "action_run_id": str(action_run.id),
            "tenant_id": tenant_id,
            "tenant_namespace": tenant_namespace,
            "principal_user_id": str(user.pk),
            "principal_service_token_id": None,
            "request_payload": synopsis_payload,
            "synopsis_payload": synopsis_payload,
        },
        queue="switchboard",
    )

    logger.info(
        "Enqueued synopsis_linkedin action_run=%s user=%s piece=%s",
        action_run.id,
        user.pk,
        piece_id,
    )

    return JsonResponse({"action_run_id": str(action_run.id)}, status=202)


_VALID_REFINE_LENGTHS = frozenset({"preserve", "shorten", "expand"})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def refine_async_proxy(request):
    source_text = (request.data.get("source_text") or "").strip()
    refinement_instruction = (request.data.get("refinement_instruction") or "").strip()
    target_length = (request.data.get("target_length") or "").strip().lower() or None
    additional_context = (request.data.get("additional_context") or "").strip() or None
    surface = (request.data.get("surface") or "console").strip()
    deferred = bool(request.data.get("deferred", False))

    if not source_text:
        return JsonResponse({"detail": "source_text is required."}, status=400)
    if not refinement_instruction:
        return JsonResponse({"detail": "refinement_instruction is required."}, status=400)
    if target_length and target_length not in _VALID_REFINE_LENGTHS:
        return JsonResponse(
            {"detail": f"target_length must be one of: {', '.join(sorted(_VALID_REFINE_LENGTHS))}."},
            status=400,
        )
    if surface not in _VALID_SURFACES:
        surface = "console"

    tenant_id = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", _DEFAULT_TENANT_ID))
    tenant_namespace = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", _DEFAULT_TENANT_NAMESPACE))

    refine_payload = {
        "source_text": source_text,
        "refinement_instruction": refinement_instruction,
        "target_length": target_length,
        "additional_context": additional_context,
    }

    execution_mode = ActionRunExecutionMode.CLOUD if deferred else ActionRunExecutionMode.LOCAL

    action_run = ActionRun.objects.create(
        tool_name=f"{surface}.refine",
        status=ActionRunStatus.PENDING,
        execution_mode=execution_mode,
        tenant_id=tenant_id,
        tenant_namespace=tenant_namespace,
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id=str(request.user.pk),
        request_payload={
            "source_text": source_text if deferred else None,
            "source_text_length": len(source_text),
            "refinement_instruction": refinement_instruction,
            "target_length": target_length,
            "additional_context": additional_context,
            "surface": surface,
            "deferred": deferred,
        },
    )

    if not deferred:
        celery_app.send_task(
            "switchboard.refine_async",
            kwargs={
                "action_run_id": str(action_run.id),
                "tenant_id": tenant_id,
                "tenant_namespace": tenant_namespace,
                "principal_user_id": str(request.user.pk),
                "principal_service_token_id": None,
                "request_payload": refine_payload,
                "refine_payload": refine_payload,
            },
            queue="switchboard",
        )
        logger.info(
            "Enqueued refine action_run=%s user=%s surface=%s",
            action_run.id,
            request.user.pk,
            surface,
        )
    else:
        logger.info(
            "Created deferred refine action_run=%s user=%s surface=%s (awaiting approval)",
            action_run.id,
            request.user.pk,
            surface,
        )

    return JsonResponse({"action_run_id": str(action_run.id)}, status=202)


_VALID_CONTENT_TYPES = frozenset({"email", "sop", "summary", "message", "document", "proposal"})
_VALID_TONES = frozenset({"professional", "friendly", "direct", "formal", "casual"})
_VALID_LENGTHS = frozenset({"brief", "standard", "detailed"})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def draft_async_proxy(request):
    content_type = (request.data.get("content_type") or "").strip().lower()
    source_text = (request.data.get("source_text") or "").strip()
    tone = (request.data.get("tone") or "").strip().lower() or None
    target_length = (request.data.get("target_length") or "").strip().lower() or None
    audience = (request.data.get("audience") or "").strip() or None
    additional_context = (request.data.get("additional_context") or "").strip() or None
    surface = (request.data.get("surface") or "console").strip()
    # deferred=true: create ActionRun without dispatching; caller approves via approve endpoint
    deferred = bool(request.data.get("deferred", False))

    if not content_type:
        return JsonResponse({"detail": "content_type is required."}, status=400)
    if content_type not in _VALID_CONTENT_TYPES:
        return JsonResponse(
            {"detail": f"content_type must be one of: {', '.join(sorted(_VALID_CONTENT_TYPES))}."},
            status=400,
        )
    if not source_text:
        return JsonResponse({"detail": "source_text is required."}, status=400)
    if tone and tone not in _VALID_TONES:
        return JsonResponse(
            {"detail": f"tone must be one of: {', '.join(sorted(_VALID_TONES))}."},
            status=400,
        )
    if target_length and target_length not in _VALID_LENGTHS:
        return JsonResponse(
            {"detail": f"target_length must be one of: {', '.join(sorted(_VALID_LENGTHS))}."},
            status=400,
        )
    if surface not in _VALID_SURFACES:
        surface = "console"

    tenant_id = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", _DEFAULT_TENANT_ID))
    tenant_namespace = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", _DEFAULT_TENANT_NAMESPACE))

    draft_payload = {
        "content_type": content_type,
        "source_text": source_text,
        "tone": tone,
        "target_length": target_length,
        "audience": audience,
        "additional_context": additional_context,
    }

    execution_mode = ActionRunExecutionMode.CLOUD if deferred else ActionRunExecutionMode.LOCAL

    action_run = ActionRun.objects.create(
        tool_name=f"{surface}.draft",
        status=ActionRunStatus.PENDING,
        execution_mode=execution_mode,
        tenant_id=tenant_id,
        tenant_namespace=tenant_namespace,
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id=str(request.user.pk),
        request_payload={
            "content_type": content_type,
            # Store full source_text for deferred runs — approve endpoint needs it to redispatch
            "source_text": source_text if deferred else None,
            "source_text_length": len(source_text),
            "tone": tone,
            "target_length": target_length,
            "audience": audience,
            "additional_context": additional_context,
            "surface": surface,
            "deferred": deferred,
        },
    )

    if not deferred:
        celery_app.send_task(
            "switchboard.draft_async",
            kwargs={
                "action_run_id": str(action_run.id),
                "tenant_id": tenant_id,
                "tenant_namespace": tenant_namespace,
                "principal_user_id": str(request.user.pk),
                "principal_service_token_id": None,
                "request_payload": draft_payload,
                "draft_payload": draft_payload,
            },
            queue="switchboard",
        )
        logger.info(
            "Enqueued draft action_run=%s user=%s content_type=%s surface=%s",
            action_run.id,
            request.user.pk,
            content_type,
            surface,
        )
    else:
        logger.info(
            "Created deferred draft action_run=%s user=%s content_type=%s surface=%s (awaiting approval)",
            action_run.id,
            request.user.pk,
            content_type,
            surface,
        )

    return JsonResponse({"action_run_id": str(action_run.id)}, status=202)


# ---------------------------------------------------------------------------
# Beryl group search (ADR: beryl-search-spec.md)
# Synchronous: retrieve from Stackroom → synthesize via Inkwell → return answer
# ---------------------------------------------------------------------------

def _source_label_from_path(source_path: str) -> str:
    """Best-effort human label derived from a Stackroom source path."""
    if source_path.startswith("almanac/events/"):
        return "Event"
    if source_path.startswith("writing_pieces/groups/"):
        return "Group Post"
    if source_path.startswith("threadworks/"):
        return "Discussion"
    if source_path.startswith("drops/"):
        return "Drop"
    return "Document"


def _frontend_url_from_chunk(chunk: dict) -> str:
    """Build a best-effort relative frontend URL from Stackroom chunk metadata."""
    artifact_type = chunk.get("artifact_type", "")
    artifact_id   = chunk.get("artifact_id", "")
    if not artifact_id:
        return ""
    if artifact_type in ("almanac.event", "almanac_event"):
        return f"/almanac/events/{artifact_id}"
    if artifact_type in ("writing.writingpiece", "writing_piece"):
        return f"/writing/{artifact_id}"
    if artifact_type in ("threadworks.discussion", "threadworks_discussion"):
        return f"/discussions/{artifact_id}"
    if artifact_type == "drop.drop":
        return f"/groups/drops/{artifact_id}"
    return ""


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def group_search_proxy(request):
    serializer = GroupSearchSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    data        = serializer.validated_data
    group_id    = data["group_id"]
    query       = data["query"]
    max_results = data["max_results"]

    from groups.models import Group
    from initiatives.services.agent_stackroom import AgentStackroomError, retrieve_from_stackroom
    from inkwell.client import InkwellUnavailableError, service_generate
    from inkwell.stackroom_http_client import get_or_create_group_library
    from switchboard.prompts.group_search_v1 import format_system_prompt, format_user_prompt

    try:
        group = Group.objects.get(pk=group_id)
    except Group.DoesNotExist:
        return JsonResponse({"detail": "Group not found."}, status=404)

    library_id = get_or_create_group_library(group)

    try:
        raw_chunks = retrieve_from_stackroom(
            query=query,
            library_id=library_id,
            limit=max_results,
        )
    except AgentStackroomError as exc:
        http_status = 504 if exc.status_code == 504 else 502
        return JsonResponse({"detail": exc.detail}, status=http_status)

    if not raw_chunks:
        return JsonResponse({
            "answer": f"I couldn't find that in {group.title}'s data.",
            "found": False,
            "sources": [],
        })

    chunks_for_prompt = [
        {
            "text": c["text"],
            "source_label": _source_label_from_path(c.get("source_file_id", "")),
        }
        for c in raw_chunks
    ]

    system_prompt = format_system_prompt(group_name=group.title)
    user_prompt   = format_user_prompt(
        group_name=group.title,
        query=query,
        chunks=chunks_for_prompt,
    )

    _ANSWER_SCHEMA = {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "found": {"type": "boolean"},
            "used_chunk_indices": {"type": "array", "items": {"type": "integer"}},
        },
        "required": ["answer", "found", "used_chunk_indices"],
    }

    try:
        inkwell_result = service_generate(
            system_prompt=system_prompt,
            prompt=user_prompt,
            schema=_ANSWER_SCHEMA,
            max_tokens=512,
            temperature=0.1,
        )
    except InkwellUnavailableError as exc:
        return JsonResponse({"detail": str(exc)}, status=502)

    result = inkwell_result.get("result", {})
    answer = result.get("answer", f"I couldn't find that in {group.title}'s data.")
    found  = result.get("found", False)
    used_indices = set(result.get("used_chunk_indices", []))

    sources = []
    for i, chunk in enumerate(raw_chunks):
        if used_indices and i not in used_indices:
            continue
        sources.append({
            "label": _source_label_from_path(chunk.get("source_file_id", "")),
            "url": _frontend_url_from_chunk(chunk),
            "excerpt": chunk["text"][:200],
        })
        if len(sources) >= 3:
            break

    return JsonResponse({
        "answer": answer,
        "found": found,
        "sources": sources,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agent_track_proxy(request):
    """
    agent.track — fetch or append items on a sponsor-scoped "Tracked" List.

    Body:
      action      "fetch" | "append"  (default "fetch")
      text        str  (required when action="append")
      group_slug  str  (optional; omit for personal context)
    """
    from django.contrib.contenttypes.models import ContentType
    from groups.models.group import Group
    from groups.models.membership import GroupMembership
    from lists.models import List as UserList

    action = request.data.get("action", "fetch")
    group_slug = (request.data.get("group_slug") or "").strip()
    text = (request.data.get("text") or "").strip()
    user = request.user

    if action == "append" and not text:
        return JsonResponse({"detail": "text is required for action=append"}, status=400)
    if action not in ("fetch", "append"):
        return JsonResponse({"detail": "action must be 'fetch' or 'append'"}, status=400)

    user_ct = ContentType.objects.get_for_model(user.__class__)

    if group_slug:
        group = Group.objects.filter(slug=group_slug, deleted_at__isnull=True).first()
        if not group:
            return JsonResponse({"detail": "Group not found"}, status=404)
        if not user.is_staff:
            group_ct = ContentType.objects.get_for_model(Group)
            if not GroupMembership.objects.filter(
                group_id=group.pk,
                member_content_type=user_ct,
                member_object_id=user.pk,
                deleted_at__isnull=True,
            ).exists():
                return JsonResponse({"detail": "Not a member of this group"}, status=403)
        sponsor_ct = ContentType.objects.get_for_model(Group)
        sponsor_id = str(group.pk)
    else:
        sponsor_ct = user_ct
        sponsor_id = str(user.pk)

    LIST_TITLE = "Tracked"

    action_run = ActionRun.objects.create(
        tool_name="agent.track",
        status=ActionRunStatus.RUNNING,
        execution_mode=ActionRunExecutionMode.LOCAL,
        tenant_id=_DEFAULT_TENANT_ID,
        tenant_namespace=_DEFAULT_TENANT_NAMESPACE,
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id=str(user.pk),
        request_payload={"action": action, "group_slug": group_slug, "text": text},
        started_at=timezone.now(),
    )

    try:
        lst = UserList.objects.filter(
            sponsor_content_type=sponsor_ct,
            sponsor_object_id=sponsor_id,
            title=LIST_TITLE,
            deleted_at__isnull=True,
        ).first()

        if action == "fetch":
            items: list[str] = []
            if lst:
                items = [
                    line.lstrip("- ").strip()
                    for line in lst.body_text.split("\n")
                    if line.strip()
                ]
            result_payload = {
                "action": "fetch",
                "items": items,
                "list_id": str(lst.id) if lst else None,
                "list_title": LIST_TITLE,
            }
        else:
            if lst is None:
                lst = UserList.objects.create(
                    title=LIST_TITLE,
                    body_text="",
                    submitted_by=user,
                    author=user,
                    sponsor_content_type=sponsor_ct,
                    sponsor_object_id=sponsor_id,
                )
            lst.body_text = (lst.body_text.rstrip("\n") + f"\n- {text}").lstrip("\n")
            lst.save(update_fields=["body_text", "updated_at"])
            result_payload = {
                "action": "append",
                "items_added": 1,
                "list_id": str(lst.id),
                "list_title": LIST_TITLE,
            }

        action_run.status = ActionRunStatus.SUCCEEDED
        action_run.result_payload = result_payload
        action_run.completed_at = timezone.now()
        action_run.save(update_fields=["status", "result_payload", "completed_at", "updated_at"])
        return JsonResponse({**result_payload, "action_run_id": str(action_run.id)}, status=200)

    except Exception as exc:
        action_run.status = ActionRunStatus.FAILED
        action_run.error_payload = {"error": str(exc)}
        action_run.completed_at = timezone.now()
        action_run.save(update_fields=["status", "error_payload", "completed_at", "updated_at"])
        raise
