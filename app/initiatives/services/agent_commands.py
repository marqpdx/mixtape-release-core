from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.utils.dateparse import parse_datetime

from initiatives.models import (
    AgentCommand,
    AgentCommandResultType,
    AgentCommandStatus,
    Initiative,
    Note,
    Reminder,
    Task,
)
from lists.models import List as MixtapeList


User = get_user_model()


def _coerce_datetime(value):
    if not value or not isinstance(value, str):
        return value
    parsed = parse_datetime(value)
    return parsed or value


def resolve_content_type_for_sponsor_model(sponsor_model: str) -> ContentType:
    if "." in sponsor_model:
        app_label, model = sponsor_model.split(".", 1)
        return ContentType.objects.get(app_label=app_label, model=model)
    return ContentType.objects.get(app_label="groups", model=sponsor_model)


@dataclass(frozen=True)
class AgentCommandTarget:
    initiative: Initiative | None
    sponsor_content_type: ContentType
    sponsor_object_id: UUID


def _resolve_target(
    *,
    initiative_id: UUID | None = None,
    sponsor_model: str | None = None,
    sponsor_id: UUID | None = None,
) -> AgentCommandTarget:
    initiative = None
    if initiative_id is not None:
        initiative = Initiative.objects.select_related("sponsor_content_type").get(pk=initiative_id)
        return AgentCommandTarget(
            initiative=initiative,
            sponsor_content_type=initiative.sponsor_content_type,
            sponsor_object_id=initiative.sponsor_object_id,
        )

    if sponsor_model is None or sponsor_id is None:
        raise ValueError("initiative_id or sponsor_model + sponsor_id is required")

    content_type = resolve_content_type_for_sponsor_model(sponsor_model)
    model_class = content_type.model_class()
    if model_class is None:
        raise ValueError("sponsor_model must resolve to a concrete model")
    model_class.objects.get(pk=sponsor_id)
    return AgentCommandTarget(
        initiative=None,
        sponsor_content_type=content_type,
        sponsor_object_id=sponsor_id,
    )


def create_note_from_agent(
    *,
    created_by: User,
    body: str,
    title: str = "",
    capture_mode: str = "typed",
    origin: str = "agent",
    raw_input: str = "",
    parsed_metadata: dict | None = None,
    initiative_id: UUID | None = None,
    sponsor_model: str | None = None,
    sponsor_id: UUID | None = None,
) -> Note:
    target = _resolve_target(
        initiative_id=initiative_id,
        sponsor_model=sponsor_model,
        sponsor_id=sponsor_id,
    )
    return Note.objects.create(
        initiative=target.initiative,
        sponsor_content_type=target.sponsor_content_type,
        sponsor_object_id=target.sponsor_object_id,
        title=title,
        body=body,
        capture_mode=capture_mode,
        origin=origin,
        raw_input=raw_input,
        parsed_metadata=parsed_metadata or {},
        created_by=created_by,
    )


def create_reminder_from_agent(
    *,
    created_by: User,
    body: str,
    remind_at,
    title: str = "",
    capture_mode: str = "typed",
    origin: str = "agent",
    raw_input: str = "",
    parsed_metadata: dict | None = None,
    initiative_id: UUID | None = None,
    sponsor_model: str | None = None,
    sponsor_id: UUID | None = None,
) -> Reminder:
    target = _resolve_target(
        initiative_id=initiative_id,
        sponsor_model=sponsor_model,
        sponsor_id=sponsor_id,
    )
    return Reminder.objects.create(
        initiative=target.initiative,
        sponsor_content_type=target.sponsor_content_type,
        sponsor_object_id=target.sponsor_object_id,
        title=title,
        body=body,
        remind_at=remind_at,
        capture_mode=capture_mode,
        origin=origin,
        raw_input=raw_input,
        parsed_metadata=parsed_metadata or {},
        created_by=created_by,
    )


def create_task_from_agent(
    *,
    created_by: User,
    title: str,
    details: str = "",
    due_at=None,
    assigned_to_id: UUID | None = None,
    status: str = "todo",
    capture_mode: str = "typed",
    origin: str = "agent",
    raw_input: str = "",
    parsed_metadata: dict | None = None,
    initiative_id: UUID | None = None,
    sponsor_model: str | None = None,
    sponsor_id: UUID | None = None,
) -> Task:
    target = _resolve_target(
        initiative_id=initiative_id,
        sponsor_model=sponsor_model,
        sponsor_id=sponsor_id,
    )
    assigned_to = None
    if assigned_to_id is not None:
        assigned_to = User.objects.get(pk=assigned_to_id)

    return Task.objects.create(
        initiative=target.initiative,
        sponsor_content_type=target.sponsor_content_type,
        sponsor_object_id=target.sponsor_object_id,
        title=title,
        details=details,
        status=status,
        due_at=due_at,
        assigned_to=assigned_to,
        capture_mode=capture_mode,
        origin=origin,
        raw_input=raw_input,
        parsed_metadata=parsed_metadata or {},
        created_by=created_by,
    )


def _normalize_items(raw) -> list[str]:
    """Coerce Inkwell's items field to a flat list of non-empty strings."""
    if isinstance(raw, list):
        return [str(i).strip() for i in raw if str(i).strip()]
    if isinstance(raw, str) and raw.strip():
        return [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]
    return []


def add_items_from_agent(
    *,
    created_by: User,
    target_name: str,
    items: list[str],
    capture_mode: str = "typed",
    raw_input: str = "",
    parsed_metadata: dict | None = None,
    initiative_id: UUID | None = None,
    sponsor_model: str | None = None,
    sponsor_id: UUID | None = None,
) -> tuple[MixtapeList, list[str]]:
    """
    Find (or create) the named list for the sponsor and append items to it.
    Returns (list_obj, added_items).
    """
    target = _resolve_target(
        initiative_id=initiative_id,
        sponsor_model=sponsor_model,
        sponsor_id=sponsor_id,
    )
    slug_query = target_name.lower().replace(" ", "-")
    lst = (
        MixtapeList.objects.filter(
            sponsor_content_type=target.sponsor_content_type,
            sponsor_object_id=target.sponsor_object_id,
            deleted_at__isnull=True,
        )
        .filter(Q(title__icontains=target_name) | Q(slug__icontains=slug_query))
        .order_by("-updated_at")
        .first()
    )

    if lst is None:
        lst = MixtapeList.objects.create(
            sponsor_content_type=target.sponsor_content_type,
            sponsor_object_id=target.sponsor_object_id,
            title=target_name,
            submitted_by=created_by,
            body_text="",
        )

    appended = "\n".join(f"- {item}" for item in items)
    lst.body_text = (lst.body_text.rstrip("\n") + "\n" + appended).lstrip("\n")
    lst.save(update_fields=["body_text", "updated_at"])
    return lst, items


def summarize_parsed_command(parsed_result: dict) -> tuple[str, str, str, bool, str]:
    normalized = parsed_result.get("normalized_payload") or {}
    ambiguities = parsed_result.get("ambiguities") or []

    title = (
        normalized.get("title")
        or normalized.get("subject")
        or normalized.get("query")
        or normalized.get("topic")
        or ""
    )
    summary = (
        normalized.get("summary")
        or normalized.get("body")
        or normalized.get("details")
        or normalized.get("prompt")
        or ""
    )
    generated_text = normalized.get("generated_text") or normalized.get("draft_text") or ""
    needs_clarification = bool(
        ambiguities
        or parsed_result.get("needs_clarification")
        or parsed_result.get("needs_confirmation")
    )
    clarification_reason = parsed_result.get("clarification_reason") or ""
    if not clarification_reason and ambiguities:
        clarification_reason = str(ambiguities[0])
    return title, summary, generated_text, needs_clarification, clarification_reason


def execute_agent_command(
    *,
    command: AgentCommand,
    confirmed_fields: dict,
    confirmed_by: User,
) -> AgentCommand:
    payload = {**(command.parsed_fields or {}), **(confirmed_fields or {})}
    parsed_metadata = {
        "entities": (command.parse_metadata or {}).get("parsed_entities", {}),
        "ambiguities": (command.parse_metadata or {}).get("ambiguities", []),
    }

    result_payload: dict
    routing_metadata: dict

    if command.parsed_verb == "note":
        note = create_note_from_agent(
            created_by=confirmed_by,
            initiative_id=command.initiative_id,
            sponsor_model=command.sponsor_content_type.model if command.sponsor_content_type else None,
            sponsor_id=command.sponsor_object_id,
            title=payload.get("title") or command.parsed_title,
            body=payload.get("body") or payload.get("summary") or command.parsed_summary or command.raw_input,
            capture_mode=command.capture_mode,
            raw_input=command.raw_input,
            parsed_metadata=parsed_metadata,
        )
        result_payload = {
            "object_type": "note",
            "note": {
                "id": str(note.id),
                "title": note.title,
                "body": note.body,
            },
        }
        routing_metadata = {
            "deep_link_type": "internal",
            "target_screen": "initiative_note_detail",
            "target_params": {"note_id": str(note.id)},
        }
    elif command.parsed_verb == "remind":
        reminder = create_reminder_from_agent(
            created_by=confirmed_by,
            initiative_id=command.initiative_id,
            sponsor_model=command.sponsor_content_type.model if command.sponsor_content_type else None,
            sponsor_id=command.sponsor_object_id,
            title=payload.get("title") or command.parsed_title,
            body=payload.get("body") or payload.get("summary") or command.parsed_summary or command.raw_input,
            remind_at=_coerce_datetime(payload.get("remind_at")),
            capture_mode=command.capture_mode,
            raw_input=command.raw_input,
            parsed_metadata=parsed_metadata,
        )
        result_payload = {
            "object_type": "reminder",
            "reminder": {
                "id": str(reminder.id),
                "title": reminder.title,
                "body": reminder.body,
                "remind_at": reminder.remind_at.isoformat(),
            },
        }
        routing_metadata = {
            "deep_link_type": "internal",
            "target_screen": "initiative_reminder_detail",
            "target_params": {"reminder_id": str(reminder.id)},
        }
    elif command.parsed_verb == "task":
        task = create_task_from_agent(
            created_by=confirmed_by,
            initiative_id=command.initiative_id,
            sponsor_model=command.sponsor_content_type.model if command.sponsor_content_type else None,
            sponsor_id=command.sponsor_object_id,
            title=payload.get("title") or command.parsed_title or command.raw_input,
            details=payload.get("details") or payload.get("summary") or command.parsed_summary,
            due_at=_coerce_datetime(payload.get("due_at")),
            assigned_to_id=payload.get("assigned_to_id"),
            capture_mode=command.capture_mode,
            raw_input=command.raw_input,
            parsed_metadata=parsed_metadata,
        )
        result_payload = {
            "object_type": "task",
            "task": {
                "id": str(task.id),
                "title": task.title,
                "details": task.details,
                "status": task.status,
            },
        }
        routing_metadata = {
            "deep_link_type": "internal",
            "target_screen": "initiative_task_detail",
            "target_params": {"task_id": str(task.id)},
        }
    elif command.parsed_verb == "add":
        target_name = payload.get("target_name") or payload.get("target") or "Untitled list"
        raw_items = payload.get("items") or payload.get("target_items") or []
        items = _normalize_items(raw_items)
        if not items:
            items = [command.raw_input]

        lst, added = add_items_from_agent(
            created_by=confirmed_by,
            initiative_id=command.initiative_id,
            sponsor_model=command.sponsor_content_type.model if command.sponsor_content_type else None,
            sponsor_id=command.sponsor_object_id,
            target_name=target_name,
            items=items,
            capture_mode=command.capture_mode,
            raw_input=command.raw_input,
            parsed_metadata=parsed_metadata,
        )
        result_payload = {
            "object_type": "list",
            "list": {
                "id": str(lst.id),
                "title": lst.title,
                "slug": lst.slug,
                "added_items": added,
                "item_count": lst.body_text.count("\n- ") + (1 if lst.body_text.startswith("- ") else 0),
            },
        }
        routing_metadata = {
            "deep_link_type": "tab",
            "target_screen": "Initiatives",
        }
    elif command.parsed_verb == "research":
        from initiatives.services.agent_research import AgentResearchError, research_via_inkwell

        query = payload.get("query") or command.parsed_title or command.raw_input
        try:
            research_result = research_via_inkwell(query=query)
        except AgentResearchError as exc:
            command.status = AgentCommandStatus.FAILED
            command.error_payload = {"detail": exc.detail}
            command.save(update_fields=["status", "error_payload", "updated_at"])
            raise

        sources = research_result.get("sources") or []
        result_payload = {
            "object_type": "research_results",
            "query": query,
            "result": research_result.get("result") or "",
            "sources": [
                {"title": s.get("title", ""), "url": s.get("url", ""), "excerpt": s.get("excerpt", "")}
                for s in sources
            ],
            "confidence": research_result.get("confidence", 0.0),
            "method": research_result.get("method", "llm"),
        }
        first_url = sources[0].get("url") if sources else None
        routing_metadata = (
            {"deep_link_type": "external_url", "external_url": first_url}
            if first_url
            else {"deep_link_type": "tab", "target_screen": "Initiatives"}
        )
    else:
        command.status = AgentCommandStatus.FAILED
        command.error_payload = {
            "detail": f"Verb '{command.parsed_verb}' is not implemented for confirm yet."
        }
        command.save(update_fields=["status", "error_payload", "updated_at"])
        raise NotImplementedError(f"Unsupported agent command verb: {command.parsed_verb}")

    result_type = (
        AgentCommandResultType.GENERATED_ARTIFACT
        if command.parsed_verb == "research"
        else AgentCommandResultType.ACKNOWLEDGMENT
    )

    command.edited_fields = confirmed_fields or {}
    command.status = AgentCommandStatus.EXECUTED
    command.executed_verb = command.parsed_verb
    command.result_type = result_type
    command.result_payload = result_payload
    command.error_payload = {}
    command.follow_up_suggestions = []
    command.routing_metadata = routing_metadata
    command.save(
        update_fields=[
            "edited_fields",
            "status",
            "executed_verb",
            "result_type",
            "result_payload",
            "error_payload",
            "follow_up_suggestions",
            "routing_metadata",
            "updated_at",
        ]
    )
    return command
